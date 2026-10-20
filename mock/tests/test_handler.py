"""Invoke the Lambda handler with API Gateway HTTP API (v2) events. Run: python3 -m unittest -v"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambda"))
import handler as h  # noqa: E402


def call(method, path, query=None, body=None):
    ev = {"requestContext": {"http": {"method": method}}, "rawPath": "/api/v1" + path,
          "queryStringParameters": query or None, "body": json.dumps(body) if body is not None else None}
    r = h.handler(ev)
    return r["statusCode"], (json.loads(r["body"]) if r["body"] else None)


class Nsif(unittest.TestCase):
    def test_health_matches_data(self):
        s, b = call("GET", "/health")
        self.assertEqual((s, b["status"]), (200, "ok"))
        self.assertEqual(b["total_students"], len(h.STUDENTS))

    def test_terms_chronological_and_sum(self):
        _, b = call("GET", "/terms")
        keys = [(t["term_year"], t["term_season"]) for t in b["terms"]]
        self.assertEqual(keys, sorted(keys, key=lambda k: (k[0], h.SEASON_ORDER[k[1]])))
        self.assertEqual(sum(t["count"] for t in b["terms"]), len(h.STUDENTS))

    def test_stats_consistent_with_terms(self):
        _, b = call("GET", "/stats")
        self.assertEqual(sum(b["terms"].values()), b["total_students"])
        _, t = call("GET", "/stats/term/F24")
        self.assertEqual(t["terms"], {"F24": t["total_students"]})
        self.assertNotIn("exp_employment", b["experience_preferences"])
        self.assertNotIn("exp_coop", b["experience_preferences"])

    def test_student_lookups(self):
        sid = h.PERSONAS[0]["student_id"]
        s, rec = call("GET", f"/students/{sid}")
        self.assertEqual(s, 200)
        _, byn = call("GET", f"/students/by-netid/{h.PERSONAS[0]['net_id']}")
        self.assertEqual(rec, byn)
        _, hist = call("GET", f"/students/{sid}/history")
        self.assertEqual(hist[0], rec)
        self.assertEqual(call("GET", "/students/nope"), (404, {"detail": "Student not found"}))
        self.assertEqual(call("GET", "/students/by-netid/nope")[0], 404)

    def test_history_newest_first_for_multi_term(self):
        multi = next(i for i in {s["student_id"] for s in h.STUDENTS}
                     if sum(1 for s in h.STUDENTS if s["student_id"] == i) > 1)
        _, hist = call("GET", f"/students/{multi}/history")
        keys = [h._term_key(r) for r in hist]
        self.assertEqual(keys, sorted(keys, reverse=True))

    def test_demo_sample_personas_first(self):
        s, b = call("GET", "/students/demo-sample", {"count": "30"})
        self.assertEqual(s, 200)
        labels = [x.get("persona_label") for x in b["students"][: len(h.PERSONAS)]]
        self.assertIn("Mei Tanaka \u2014 Freshman, Computer Science", labels)
        self.assertLessEqual(len(b["students"]), 30)
        self.assertEqual(b["total_in_db"], len(h.STUDENTS))
        self.assertRegex(b["students"][0]["display_label"], r".+ - .+ - .+ \(F\d\d\)")

    def test_search_semantics(self):
        _, b = call("POST", "/students/search", body={"career_interests": ["career_health", "career_research"]})
        for s in b["students"]:
            self.assertTrue({"career_health", "career_research"} <= set(s["career_interests"]))
        _, b = call("POST", "/students/search", body={"research_domains": ["engineering", "law_policy"]})
        for s in b["students"]:
            self.assertTrue({"engineering", "law_policy"} & set(s["research_domains"]))
        _, b = call("POST", "/students/search", body={"college": "NURSING"})
        self.assertTrue(b["total"] > 0 and all("nursing" in s["college"].lower() for s in b["students"]))

    def test_search_pagination_and_validation(self):
        _, b = call("POST", "/students/search", body={"page": 2, "page_size": 5})
        self.assertEqual((b["page"], b["page_size"], len(b["students"])), (2, 5, 5))
        for bad in ({"page": 0}, {"page_size": 101}, {"page_size": 0}, {"career_interests": "x"}):
            s, e = call("POST", "/students/search", body=bad)
            self.assertEqual(s, 422, bad)
            self.assertIsInstance(e["detail"], list)

    def test_routing_errors(self):
        self.assertEqual(call("GET", "/nope")[0], 404)
        self.assertEqual(call("DELETE", "/health")[0], 405)
        r = h.handler({"requestContext": {"http": {"method": "POST"}}, "rawPath": "/api/v1/students/search",
                       "body": "{bad"})
        self.assertEqual(r["statusCode"], 422)


class RestApiEvent(unittest.TestCase):
    """REST API (payload v1) proxy events use `path` + `httpMethod`, not rawPath/requestContext.http."""

    def test_v1_get_and_post(self):
        r = h.handler({"httpMethod": "GET", "path": "/api/v1/students/by-netid/mei.demo",
                       "queryStringParameters": None, "pathParameters": {"proxy": "students/by-netid/mei.demo"},
                       "requestContext": {"stage": "prod"}, "body": None, "isBase64Encoded": False})
        self.assertEqual(r["statusCode"], 200)
        rec = json.loads(r["body"])
        r = h.handler({"httpMethod": "POST", "path": "/api/v1/matches", "queryStringParameters": None,
                       "body": json.dumps({"student": rec, "limit": 3}), "isBase64Encoded": False})
        self.assertEqual(len(json.loads(r["body"])["matches"]), 3)
        self.assertIn("access-control-allow-origin", r["headers"])


class Extensions(unittest.TestCase):
    def test_student_courses(self):
        _, b = call("GET", f"/students/{h.PERSONAS[0]['student_id']}/courses")
        self.assertTrue(b["terms"] and all(t["courses"] for t in b["terms"]))
        self.assertEqual(call("GET", "/students/nope/courses")[0], 404)

    def test_courses_departments_programs(self):
        _, c = call("GET", "/courses", {"subject": "csc", "page_size": "5"})
        self.assertTrue(c["total"] > 0 and all(x["subject"] == "CSC" for x in c["courses"]))
        _, d = call("GET", "/departments", {"has_courses": "true"})
        self.assertTrue(0 < d["total"] < len(h.DEPARTMENTS))
        _, p = call("GET", "/programs", {"page_size": "3"})
        pid = p["programs"][0]["id"]
        self.assertEqual(call("GET", f"/programs/{pid}")[1]["id"], pid)
        self.assertEqual(call("GET", "/programs/zzz")[0], 404)

    def test_faculty(self):
        _, f = call("GET", "/faculty", {"college": "science", "page_size": "10"})
        self.assertTrue(f["total"] > 0 and len(f["faculty"]) <= 10)
        fid = f["faculty"][0]["faculty_id"]
        _, one = call("GET", f"/faculty/{fid}")
        self.assertTrue(one["project"]["inferred"])
        self.assertEqual(call("GET", "/faculty/zzz")[0], 404)
        _, o = call("GET", "/faculty", {"status": "open", "page_size": "100"})
        self.assertTrue(all(x["project"]["application_status"] == "open" for x in o["faculty"]))


class Matching(unittest.TestCase):
    def match(self, net, **kw):
        _, rec = call("GET", f"/students/by-netid/{net}")
        s, b = call("POST", "/matches", body={"student": rec, **kw})
        self.assertEqual(s, 200)
        return b

    def test_scores_sorted_and_bounded(self):
        b = self.match("mei.demo", limit=15)
        pcts = [m["match"]["percent"] for m in b["matches"]]
        self.assertEqual(pcts, sorted(pcts, reverse=True))
        self.assertTrue(all(30 <= p <= 98 for p in pcts))
        self.assertTrue(b["meta"]["heuristic"])
        self.assertTrue(all(m["match"]["reasons"] is not None for m in b["matches"]))

    def test_closed_excluded_by_default(self):
        b = self.match("mei.demo", limit=100)
        self.assertTrue(all(m["faculty"]["project"]["application_status"] != "closed" for m in b["matches"]))
        b2 = self.match("mei.demo", limit=100, preferences={"include_closed": True})
        self.assertGreater(b2["total_candidates"], b["total_candidates"])

    def test_personas_get_different_top_fields(self):
        cs = self.match("mei.demo")["matches"][:10]
        en = self.match("amara.demo")["matches"][:10]
        self.assertNotEqual({m["faculty"]["faculty_id"] for m in cs}, {m["faculty"]["faculty_id"] for m in en})
        cs_depts = " ".join((m["faculty"]["primary_department"] or "") for m in cs).lower()
        self.assertTrue(any(k in cs_depts for k in ("comput", "inform", "data", "math", "engineer", "science")))

    def test_preferences_affect_reasons(self):
        b = self.match("mei.demo", preferences={"paid": True}, limit=30)
        paid = [m for m in b["matches"] if any("paid" in r.lower() for r in m["match"]["reasons"])]
        self.assertTrue(paid)

    def test_validation(self):
        self.assertEqual(call("POST", "/matches", body={})[0], 422)
        _, rec = call("GET", f"/students/by-netid/mei.demo")
        self.assertEqual(call("POST", "/matches", body={"student": rec, "limit": 0})[0], 422)


if __name__ == "__main__":
    unittest.main()
