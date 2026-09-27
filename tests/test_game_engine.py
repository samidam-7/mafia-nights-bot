import unittest
from types import SimpleNamespace

import game_engine as engine


def user(user_id: int, name: str) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, first_name=name, username=None)


class GameEngineTests(unittest.TestCase):
    def make_game(self, roles):
        game = engine.new_game(-100)
        for index, role in enumerate(roles, start=1):
            game["players"][str(index)] = engine.new_player(user(index, f"Player {index}"))
        engine.assign_roles(game)
        for index, role in enumerate(roles, start=1):
            game["players"][str(index)]["role"] = role
            game["roles"][str(index)] = role
        game["started"] = True
        game["phase"] = "night"
        return game

    def test_doctor_revives_dead_player_once(self):
        game = self.make_game(["doctor", "mafia", "citizen"])
        game["alive"].remove("3")
        game["dead"].append("3")
        game["players"]["3"]["alive"] = False

        ok, _, _ = engine.submit_action(game, "1", "revive", "3")
        self.assertTrue(ok)
        self.assertIn("3", game["alive"])
        self.assertNotIn("3", game["dead"])
        self.assertTrue(game["doctor_used"])

        ok, message, _ = engine.submit_action(game, "1", "revive", "3")
        self.assertFalse(ok)
        self.assertIn("مسبقًا", message)

    def test_mafia_can_kill_only_alive_target(self):
        game = self.make_game(["mafia", "citizen", "citizen"])
        ok, _, _ = engine.submit_action(game, "1", "kill", "2")
        self.assertTrue(ok)
        self.assertEqual(game["night_actions"]["kill"], "2")
        self.assertIn("2", game["alive"])

        ok, _, _ = engine.submit_action(game, "1", "kill", "3")
        self.assertFalse(ok)

    def test_player_cannot_use_another_role_action(self):
        game = self.make_game(["citizen", "mafia", "doctor"])
        ok, message, _ = engine.submit_action(game, "1", "kill", "2")
        self.assertFalse(ok)
        self.assertIn("ليست من دورك", message)

    def test_clown_wins_only_by_vote(self):
        game = self.make_game(["clown", "mafia", "citizen"])
        self.assertFalse(engine.check_clown_win(game, "1", "hunter"))
        self.assertTrue(engine.check_clown_win(game, "1", "vote"))

    def test_mafia_wins_at_parity(self):
        game = self.make_game(["mafia", "citizen", "citizen"])
        game["alive"].remove("3")
        game["dead"].append("3")
        game["players"]["3"]["alive"] = False
        self.assertEqual(engine.check_winner(game), "mafia")

    def test_tied_vote_is_not_an_elimination(self):
        game = self.make_game(["mafia", "citizen", "citizen"])
        game["votes"] = {"2": "1", "3": "2"}
        self.assertEqual(engine.calculate_votes(game), "tie")


if __name__ == "__main__":
    unittest.main()