"""Every game in a profile of its own, moved without losing anything."""

from __future__ import annotations

from src.core.game_profiles import shared_settings, split_all
from src.database.database import Database
from src.utils import save_files
from src.utils.profiles import DEFAULT_PROFILE_NAME, ProfileManager


def _default_with_two_games(tmp_path) -> ProfileManager:
    profiles = ProfileManager(tmp_path)
    db = Database(profiles.db_path(DEFAULT_PROFILE_NAME))
    db.set_setting("hotkey_increment", "f7")  # the player's own key
    for name, deaths in (("Elden Ring", 3), ("Hollow Knight", 2)):
        game = db.create_game(name)
        boss = db.create_boss(game, "First Boss")
        session = db.start_session(game)
        for _ in range(deaths):
            db.add_death_event(game, boss, session, 1)
        db.add_death_template(game, "[0.3, 0.4, 0.4, 0.15]", b"\x01\x00\x01\x00\x80")
        db.set_setting(f"save_deaths_{game}", f'{{"path": "{name}.sl2"}}')
    db.close()
    return profiles


def test_each_game_gets_its_own_profile_with_everything(tmp_path) -> None:
    profiles = _default_with_two_games(tmp_path)
    moved = split_all(profiles)
    assert sorted(moved.values()) == ["Elden Ring", "Hollow Knight"]
    assert profiles.list_profiles() == [DEFAULT_PROFILE_NAME, "Elden Ring", "Hollow Knight"]

    default = Database(profiles.db_path(DEFAULT_PROFILE_NAME))
    assert default.get_games() == []
    backups = list(save_files.saves_folder(default.path).glob("Before one profile per game*"))
    assert len(backups) == 1  # the data as it was, to load back
    default.close()

    for name, deaths in (("Elden Ring", 3), ("Hollow Knight", 2)):
        db = Database(profiles.db_path(name))
        (game,) = db.get_games()
        assert game["name"] == name
        assert db.get_total_deaths(game["id"]) == deaths
        assert [b["name"] for b in db.get_bosses(game["id"])] == ["First Boss"]
        assert len(db.get_death_templates(game["id"])) == 1
        assert db.get_setting(f"save_deaths_{game['id']}", "") == f'{{"path": "{name}.sl2"}}'
        assert db.get_setting("hotkey_increment", "") == "f7"  # the settings came along
        assert db.get_setting("last_game_id", "") == str(game["id"])
        db.close()


def test_running_it_again_changes_nothing(tmp_path) -> None:
    profiles = _default_with_two_games(tmp_path)
    split_all(profiles)
    assert split_all(profiles) == {}
    assert len(profiles.list_profiles()) == 3


def test_a_profile_of_the_same_name_with_another_game_isnt_used(tmp_path) -> None:
    profiles = _default_with_two_games(tmp_path)
    profiles.create_profile("Elden Ring")
    taken = Database(profiles.db_path("Elden Ring"))
    taken.create_game("Something Else")
    taken.close()
    moved = split_all(profiles)
    assert "Elden Ring (2)" in moved.values()


def test_shared_settings_leave_out_each_games_own(tmp_path) -> None:
    db = Database(tmp_path / "d.db")
    db.set_setting("theme", "light")
    db.set_setting("save_deaths_4", "{}")
    db.set_setting("last_game_id", "4")
    assert "theme" in shared_settings(db)
    assert "save_deaths_4" not in shared_settings(db)
    assert "last_game_id" not in shared_settings(db)
    db.close()
