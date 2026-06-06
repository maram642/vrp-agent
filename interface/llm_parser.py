

import json
import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()


# ─── Configuration ────────────────────────────────────────────────────────────

GROQ_API_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL     = "llama-3.3-70b-versatile"

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL   = "claude-sonnet-4-20250514"


# ─── System prompt partagé ────────────────────────────────────────────────────

SYSTEM_PARSE = """Tu es un assistant spécialisé en logistique et optimisation de tournées (VRP).
Tu reçois une description en langage naturel de contraintes de livraison.
Extrais les contraintes et retourne UNIQUEMENT un JSON valide, sans texte autour.

Flags disponibles :
    has_time_windows      : bool   — créneaux horaires mentionnés
    needs_refrigeration   : bool   — produits frais/froids
    has_priorities        : bool   — priorités de livraison
    has_service_times     : bool   — temps de déchargement
    max_route_duration_h  : float  — durée max tournée en heures
    delivery_before       : str    — heure limite (format HH:MM)
    vehicle_type_required : str    — type véhicule requis

Exemple de réponse :
{"has_time_windows": true, "needs_refrigeration": true, "delivery_before": "14:00"}"""


# ─── Appel Groq ───────────────────────────────────────────────────────────────

def _call_groq(text: str) -> dict:
    """Appelle l'API Groq (gratuite) pour parser les contraintes."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {}

    try:
        response = requests.post(
            GROQ_API_URL,
            headers={
                "Content-Type" : "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json={
                "model"      : GROQ_MODEL,
                "max_tokens" : 300,
                "temperature": 0.1,
                "messages"   : [
                    {"role": "system", "content": SYSTEM_PARSE},
                    {"role": "user",   "content": text},
                ],
            },
            timeout=20,
        )
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"].strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Groq parser : {e}")
        return {}
    except json.JSONDecodeError:
        print(f"  ❌ Groq parser : réponse non parseable")
        return {}


# ─── Appel Claude (fallback) ──────────────────────────────────────────────────

def _call_claude(text: str) -> dict:
    """Appelle Claude en fallback si Groq échoue ou indisponible."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {}

    try:
        response = requests.post(
            CLAUDE_API_URL,
            headers={
                "Content-Type"      : "application/json",
                "x-api-key"         : api_key,
                "anthropic-version" : "2023-06-01",
            },
            json={
                "model"      : CLAUDE_MODEL,
                "max_tokens" : 300,
                "system"     : SYSTEM_PARSE,
                "messages"   : [{"role": "user", "content": text}],
            },
            timeout=30,
        )
        response.raise_for_status()
        raw = response.json()["content"][0]["text"].strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Claude parser : {e}")
        return {}
    except json.JSONDecodeError:
        print(f"  ❌ Claude parser : réponse non parseable")
        return {}


# ─── Fallback règle-based ─────────────────────────────────────────────────────

def _parse_mock(text: str) -> dict:
   
    t     = text.lower()
    flags = {}

    if any(w in t for w in ["avant", "before", "créneau", "heure limite", "jusqu"]):
        flags["has_time_windows"] = True
        hours = re.findall(r'\b(\d{1,2})h\b|\b(\d{1,2}):(\d{2})\b', t)
        if hours:
            h = hours[0][0] or hours[0][1]
            m = hours[0][2] if hours[0][2] else "00"
            flags["delivery_before"] = f"{int(h):02d}:{m}"

    if any(w in t for w in ["frais", "froid", "frigo", "réfrigér", "cold", "surgelé"]):
        flags["needs_refrigeration"] = True

    if any(w in t for w in ["priorité", "priority", "vip", "urgent"]):
        flags["has_priorities"] = True

    m = re.search(r'(\d+)\s*h(?:eures?)?', t)
    if m and any(w in t for w in ["max", "durée", "finir", "terminer"]):
        flags["max_route_duration_h"] = float(m.group(1))

    print(f"  📋 Flags (mock) : {flags}")
    return flags


# ─── Application des flags ────────────────────────────────────────────────────

def _apply_flags(flags: dict, dataset: dict) -> None:
    """Applique les flags détectés au dataset en place."""
    orders   = dataset.get("orders", [])
    vehicles = dataset.get("vehicles", [])

    if "delivery_before" in flags:
        end_time = flags["delivery_before"]
        for o in orders:
            if not o.get("time_window"):
                o["time_window"] = {"start": "00:00", "end": end_time}
        print(f"  ✅ Time window globale : 00:00 → {end_time}")

    if "max_route_duration_h" in flags:
        max_h = float(flags["max_route_duration_h"])
        for v in vehicles:
            v["max_route_duration_h"] = max_h
        print(f"  ✅ Durée max tournée : {max_h}h")

    if flags.get("needs_refrigeration"):
        for o in orders:
            o["requires_refrigeration"] = True
        print(f"  ✅ Réfrigération activée")


# ─── Fonction principale ──────────────────────────────────────────────────────

def parse_constraints(text: str, dataset: dict) -> dict:
  
    print(f"\n  🤖 Parser : \"{text[:60]}{'...' if len(text)>60 else ''}\"")

    for call, label in [(_call_groq, "Groq"), (_call_claude, "Claude")]:
        flags = call(text)
        if flags:
            print(f"  📋 Flags ({label}) : {flags}")
            _apply_flags(flags, dataset)
            return flags

    print("  ℹ️  Pas de clé API — parser mock")
    flags = _parse_mock(text)
    _apply_flags(flags, dataset)
    return flags