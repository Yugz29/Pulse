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

        self.assertIn("- ajoute des tests pour les routes et la queue lightweight", digest)
        self.assertIn("- vérifie que le statut n'expose ni prompt ni texte généré", digest)

    def test_detecte_modeles_structs_et_services(self):
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

        self.assertIn("LightweightLLMStatusResponse", digest)
        self.assertIn("AppleFoundationWorker", digest)

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


if __name__ == "__main__":
    unittest.main()
