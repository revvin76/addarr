# Ruflo Agent Routing
- **Intent Detection:** If a task involves `app.py`, `routes.py`, `Blueprints`, or `Werkzeug`, set `routing_priority = "flask_expert"`.
- **Auto-Spawn Protocol:** If `flask_expert` is not in the active swarm, use `spawn_agent` immediately before responding.
- **Persistence:** Ensure the `flask_expert` agent retains the `session_id` to avoid re-reading the Flask documentation.