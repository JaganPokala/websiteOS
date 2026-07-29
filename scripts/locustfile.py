"""
Concurrency / load test for the /query endpoint, using Locust's own web
dashboard to drive it.

Each simulated Locust "user" signs up as a fresh account (on_start), creates
one conversation, then repeatedly posts a random question to /query with a
few seconds of "think time" in between, like a real person typing.

IMPORTANT: every request here is a real call through guardrails -> planner ->
retriever -> responder, so every one triggers real OpenAI API calls. Keep the
user count and run duration deliberate — this is not free to run.

Run it (server must already be running, e.g. `python run.py` in another
terminal):
    .venv\\Scripts\\locust.exe -f scripts/locustfile.py --host http://127.0.0.1:8000

Then open http://localhost:8089 in a browser, set:
  - Number of users : how many concurrent simulated people
  - Ramp up          : how fast they "arrive" (e.g. 1/sec)
and click Start. Watch requests/sec and the response-time percentiles
(p50/p95) climb live as load increases.
"""
import random
import uuid

from locust import HttpUser, task, between

QUESTIONS = [
    "I need a PostgreSQL database that keeps its data after Pod restarts. Which Kubernetes resources should I use, and why?",
    "My application needs configuration values, passwords, persistent storage, and external access. Which Kubernetes resources should I create?",
    "I deployed a new version of my application, but users still see the old version. What Kubernetes components should I investigate?",
    "How can I ensure exactly one copy of a monitoring agent runs on every node?",
    "Explain the complete networking path from a user on the internet to a container running inside Kubernetes.",
    "How would you deploy a highly available web application that automatically scales based on CPU usage?",
    "What Kubernetes objects are involved in exposing an application securely over HTTPS?",
    "How can you deploy an application without downtime while ensuring traffic only reaches healthy Pods?",
    "Your Pods cannot communicate with the database. Which Kubernetes resources would you inspect first?",
    "Explain how Kubernetes maintains the desired state of an application after a node failure.",
    "How does a Deployment perform a rolling update? What happens if the new Pods fail readiness checks?",
    "Explain how kubelet, kube-apiserver, and etcd work together when a Pod is created.",
    "What happens from the moment you run kubectl apply until your application is running?",
    "How does Kubernetes decide on which node to schedule a Pod?",
    "Explain the relationship between Ingress, Services, and Pods."
]


class RagUser(HttpUser):
    wait_time = between(2, 5)

    def on_start(self):
        """Runs once per simulated user before its tasks start: signup + create a conversation."""
        email = f"loadtest-{uuid.uuid4().hex[:12]}@example.com"
        password = "loadtest-pass-123"

        signup = self.client.post(
            "/auth/signup",
            json={"email": email, "password": password},
            name="/auth/signup",
        )
        signup.raise_for_status()
        token = signup.json()["access_token"]
        self.client.headers.update({"Authorization": f"Bearer {token}"})

        conv = self.client.post("/conversations", name="/conversations [create]")
        conv.raise_for_status()
        self.conversation_id = conv.json()["id"]

    @task
    def ask_question(self):
        self.client.post(
            "/query",
            json={"q": random.choice(QUESTIONS), "conversation_id": self.conversation_id},
            name="/query",
        )
