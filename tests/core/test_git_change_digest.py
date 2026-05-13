import unittest

from daemon.core.git_change_digest import build_change_digest_from_diff


class TestGitChangeDigest(unittest.TestCase):
    def test_detecte_route_ajoutee_sans_code_brut(self):
        digest = build_change_digest_from_diff("""\
diff --git a/daemon/routes/lightweight_llm.py b/daemon/routes/lightweight_llm.py
@@ -1,3 +1,8 @@
+    @app.route("/llm/lightweight/status")
+    def get_lightweight_status():
+        return jsonify(lightweight_queue.status())
""")

        self.assertIn("- ajoute une route GET /llm/lightweight/status", digest)
        self.assertNotIn("@app.route", digest)
        self.assertNotIn("return jsonify", digest)

    def test_detecte_tests_ajoutes(self):
        digest = build_change_digest_from_diff("""\
diff --git a/tests/test_lightweight_llm_routes.py b/tests/test_lightweight_llm_routes.py
@@ -1,3 +1,8 @@
+def test_status_returns_counts_and_last_result_without_content(self):
+    self.assertNotIn("prompt", payload["last_result"])
""")

        self.assertIn("- ajoute des tests de régression ou de garde-fous", digest)
        self.assertIn("- vérifie que le statut n'expose ni prompt ni texte généré", digest)

    def test_detecte_services_sans_lister_modeles_internes(self):
        digest = build_change_digest_from_diff("""\
diff --git a/App/App/DaemonBridgeModels.swift b/App/App/DaemonBridgeModels.swift
@@ -1,3 +1,8 @@
+struct LightweightLLMStatusResponse: Decodable {
+struct LightweightLLMQueueStatus: Decodable {
diff --git a/App/App/AppleFoundationWorker.swift b/App/App/AppleFoundationWorker.swift
new file mode 100644
@@ -0,0 +1,8 @@
+final class AppleFoundationWorker {
""")

        self.assertNotIn("LightweightLLMStatusResponse", digest)
        self.assertIn("AppleFoundationWorker", digest)
        self.assertNotIn("ajoute des modèles", digest)

    def test_limite_les_bullets(self):
        digest = build_change_digest_from_diff("""\
diff --git a/a.py b/a.py
@@ -1,3 +1,20 @@
+@app.route("/llm/a")
+@app.route("/llm/b")
+struct AModel: Decodable {}
+struct BModel: Decodable {}
+def alpha():
+def beta():
+def gamma():
+def delta():
+def epsilon():
diff --git a/tests/test_a.py b/tests/test_a.py
@@ -1,3 +1,4 @@
+def test_a(): pass
diff --git a/App/App/DashboardRootView.swift b/App/App/DashboardRootView.swift
@@ -1,3 +1,4 @@
+Text("Apple Foundation")
diff --git a/App/App/DaemonBridge+LLM.swift b/App/App/DaemonBridge+LLM.swift
@@ -1,3 +1,4 @@
+func getLightweightLLMStatus() async throws {}
""")

        self.assertLessEqual(len([line for line in digest.splitlines() if line.startswith("- ")]), 6)

    def test_diff_vide_retourne_vide(self):
        self.assertEqual(build_change_digest_from_diff(""), "")

    def test_logs_bornes_et_bruit_access_routiniers(self):
        digest = build_change_digest_from_diff("""\
diff --git a/daemon/main.py b/daemon/main.py
@@ -1,3 +1,12 @@
+    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3)
+    _ROUTINE_PATHS_BY_METHOD = {"GET": {"/ping", "/state", "/llm/models"}}
+    logging.getLogger("werkzeug").addFilter(_RoutineGetLogFilter())
diff --git a/tests/test_main_logging.py b/tests/test_main_logging.py
@@ -1,3 +1,5 @@
+class TestLoggingRetention(unittest.TestCase):
""")

        self.assertIn("borne les journaux du daemon", digest)
        self.assertIn("réduit le bruit des accès routiniers", digest)
        self.assertNotIn("TestLoggingRetention", digest)
        self.assertNotIn("a touché plusieurs fonctions", digest)

    def test_storage_log_retention_cleanup(self):
        digest = build_change_digest_from_diff("""\
diff --git a/daemon/storage/log_retention.py b/daemon/storage/log_retention.py
new file mode 100644
@@ -0,0 +1,20 @@
+def cleanup_old_logs(log_dir):
+    # safe retention cleanup for logs
+    return deleted
diff --git a/tests/storage/test_log_retention.py b/tests/storage/test_log_retention.py
@@ -0,0 +1,8 @@
+class TestLogRetention(unittest.TestCase):
""")

        self.assertIn("nettoyage sûr de rétention des logs", digest)
        self.assertNotIn("TestLogRetention", digest)
        self.assertNotIn("cleanup_old_logs", digest)

    def test_llm_heavy_warmup_lightweight_flows(self):
        digest = build_change_digest_from_diff("""\
diff --git a/daemon/llm/lifecycle_policy.py b/daemon/llm/lifecycle_policy.py
new file mode 100644
@@ -0,0 +1,20 @@
+def is_heavy_llm_autowarm_enabled():
+    return os.getenv("PULSE_HEAVY_LLM_AUTOWARM") == "1"
diff --git a/daemon/runtime_orchestrator.py b/daemon/runtime_orchestrator.py
@@ -1,3 +1,8 @@
+if is_heavy_llm_autowarm_enabled():
+    self._schedule_heavy_llm_warmup(reason="screen_unlocked")
diff --git a/tests/test_runtime_orchestrator.py b/tests/test_runtime_orchestrator.py
@@ -1,3 +1,5 @@
+class DummyThread:
""")

        self.assertIn("évite le warmup du modèle lourd sur les flux lightweight", digest)
        self.assertNotIn("DummyThread", digest)
        self.assertNotIn("a ajouté trois nouveaux modèles", digest)

    def test_memory_embeddings_disabled_by_default(self):
        digest = build_change_digest_from_diff("""\
diff --git a/daemon/memory/embedding_policy.py b/daemon/memory/embedding_policy.py
new file mode 100644
@@ -0,0 +1,12 @@
+def embeddings_enabled():
+    return os.getenv("PULSE_EMBEDDINGS_ENABLED") == "1"
diff --git a/daemon/memory/vector_store.py b/daemon/memory/vector_store.py
@@ -1,3 +1,8 @@
+if not embeddings_enabled():
+    return None
diff --git a/tests/memory/test_embedding_policy.py b/tests/memory/test_embedding_policy.py
@@ -0,0 +1,8 @@
+class TestEmbeddingPolicy(unittest.TestCase):
""")

        self.assertIn("désactive les embeddings par défaut", digest)
        self.assertNotIn("TestEmbeddingPolicy", digest)
        self.assertNotIn("a ajouté trois nouveaux modèles", digest)


if __name__ == "__main__":
    unittest.main()
