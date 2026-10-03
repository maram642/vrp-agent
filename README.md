# 🚛 VRP Agent — Intelligent Route Planning in a TMS
AI-powered vehicle routing system combining Google OR-Tools, KMeans clustering, and LLMs for intelligent constraint-aware route optimization.

> Final Year Project (PFA) — ENET'Com Sfax, 2026  
> **Maram Boughammoura** · Data Engineering & Decisional Making  Systems  
> Supervised by **M. Tarek Ouni**

---

## 📌 Overview

**VRP Agent** is an intelligent hybrid system for optimizing vehicle routing within a Transport Management System (TMS). It combines mathematical optimization (Google OR-Tools) with Artificial Intelligence (KMeans clustering + LLMs) to solve real-world logistics problems at industrial scale.

The system automatically identifies the VRP variant to solve, accepts constraints written in plain natural language, and produces optimized delivery routes through a modular pipeline.

---

## 🧩 Key Features

-  **Automatic VRP classification** — detects CVRP, VRPTW, MDVRP, or combinations from raw input data
-  **Geographic clustering** — KMeans on GPS coordinates to decompose large instances
-  **Google OR-Tools solver** — handles capacity, time windows, multi-depot, refrigeration, and priority constraints
-  **LLM-powered natural language parser** — users describe routing rules in plain text (e.g. *"deliver before 2pm"*)
-  **LLM solution explainer** — auto-generates human-readable summaries of optimized routes
-  **Interactive Streamlit UI** — map visualization, route tables, undelivered order tracking, JSON/CSV export
-  **100% service rate** on simple and multi-depot scenarios, with no time constraint violations

---

## 📁 Project Structure
 
```
vrp_agent/
├── data/
│   └── synthetic/
│       ├── scenario_simple.json        # CVRP — 15 orders, 3 vehicles
│       ├── scenario_large.json         # CVRP — 1000 orders, 25 vehicles
│       ├── scenario_multidepots.json   # MDVRP — 2 depots, 30 orders
│       └── scenario_timewindows.json   # VRPTW — 100 orders, 12 vehicles
├── core/
│   ├── preprocessing/
│   │   └── cleaner.py
│   ├── classification/
│   │   └── vrp_classifier.py
│   ├── clustering/
│   │   └── order_clustering.py
│   ├── strategy/
│   │   └── strategy_selector.py
│   ├── constraints/
│   │   └── constraint_manager.py
│   ├── solvers/
│   │   └── vrp_solver.py
│   └── export/
│       └── export_solution.py
├── interface/
│   ├── llm_parser.py
│   ├── llm_explainer.py
│   └── streamlit_app.py
├── tests/
│   ├── test_preprocessing.py
│   ├── test_classifier.py
│   └── test_solver.py
├── config.py
├── constraints_config.json
├── main.py
├── requirements.txt
└── README.md
```
 
---


## ⚙️ Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.11 |
| VRP Solver | Google OR-Tools 9.12 |
| Clustering | scikit-learn 1.3.2 (KMeans) |
| LLM Integration | Groq API (llama-3-70b) · Claude API (fallback) · Regex Mock (offline) |
| UI | Streamlit |
| Data Processing | Pandas 2.0.3 · NumPy 1.24.4 |
| Export | JSON · CSV |

---

## 🚀 Getting Started

### 1. Clone the repository
```bash
git clone https://github.com/maram642/vrp-agent.git
cd vrp_agent
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run via command line
```bash
python main.py --input data/synthetic/scenario_simple.json
```

### 4. Launch the Streamlit interface
```bash
streamlit run interface/streamlit_app.py
```

---

## 🧪 Test Scenarios

| Scenario | Variant | Orders | Vehicles | Depots | Highlights |
|---|---|---|---|---|---|
| `scenario_simple.json` | CVRP | 15 | 3 | 1 | Base validation |
| `scenario_large.json` | CVRP | 1 000 | 25 | 1 | KMeans clustering |
| `scenario_multidepots.json` | MDVRP | 30 | 6 | 2 | Multi-depot routing |
| `scenario_timewindows.json` | VRPTW | 100 | 12 | 1 | Time windows + cold chain |

---

## 📊 Results

- **100% service rate** on simple and multi-depot scenarios
- **97%+ service rate** on large-scale instances
- Computation times compatible with operational use
- No time constraint violations on VRPTW scenarios

---

## 🤖 LLM Integration

The system implements a **3-level fallback architecture**:

1. **Groq API** (`llama-3-70b-instruct`) — primary
2. **Claude API** (Anthropic) — secondary fallback
3. **Regex Mock Parser** — offline fallback for common constraints

---

## 👩‍💻 Author

**Maram Boughammoura**  
Data Engineering & Decisional Systems — ENET'Com Sfax  
📧 maram2.boughammoura@gmail.com  
🔗 [LinkedIn](https://www.linkedin.com/in/maram-boughammoura-492a62338/)

---

## 📄 License

This project was developed as a Final Year Academic Project (PFA) at ENET'Com Sfax.  
Academic use only.
