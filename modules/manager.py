# verifier.py

from datetime import datetime
import mysql.connector as mysql
from mysql.connector.cursor import MySQLCursorBuffered
import requests
import random
import secrets
from typing import Callable, List, Optional, Tuple, TypeVar

from modules.exceptions import TimeoutError, NotFoundError, APIError

T = TypeVar('T') 

class User:
    def __init__(self, id : int, username : str, description: str):
        self.id = id
        self.username = username
        self.description = description

    def __str__(self):
        return self.username

    @staticmethod
    def from_dict(d) -> "User":
        return User(d["id"], d["name"], d["description"])

class ExpiringPhrase:

    SECONDS_TO_EXPIRE = 15*60

    def __init__(self, roblox_id : int, phrase : str, created : datetime):
        self.roblox_id = roblox_id
        self.phrase = phrase
        self.created = created

    def is_expired(self) -> bool:
        return self.time_to_expire < 0

    def __bool__(self) -> bool:
        return not self.is_expired()

    @property
    def time_to_expire(self) -> int:
        return int(self.SECONDS_TO_EXPIRE - (datetime.now() - self.created).total_seconds()) + 1

    @staticmethod
    def from_row(row) -> "ExpiringPhrase":
        return ExpiringPhrase(row[0], row[1], row[2])

class AccountManager:

    def __init__(self, user, password):
        self.user = user
        self.password = password
        with open("files/words.txt") as file:
            self.words = file.read().split(",")

    def get_request(self, url : str, name : str) -> requests.Response:
        try:
            res = requests.get(url, timeout=5)
            if res.status_code == 404:
                raise NotFoundError
            elif res.status_code < 200 or res.status_code >= 300:
                raise APIError(name)
            else:
                return res
        except requests.Timeout:
            raise TimeoutError(name)

    def get_user_from_roblox(self, user_id : int) -> User:
        res = self.get_request(f"https://users.roblox.com/v1/users/{user_id}", "Roblox Users")
        return User.from_dict(res.json())

    def connect_and_execute(self, callback : Callable[[MySQLCursorBuffered], T]) -> T:
        with mysql.connect(
            host="127.0.0.1",
            user=self.user,
            password=self.password,
            database="discord_to_roblox",
            autocommit=True
        ) as conn:
            with conn.cursor(buffered=True) as cur:
                return callback(cur)
        
    def generate_random_phrase(self) -> str:
        return " ".join(random.sample(self.words, 20))

    def create_get_phrase_callback(self, discord_id : int) -> Callable[[MySQLCursorBuffered], Optional[ExpiringPhrase]]:
        def callback(cur : MySQLCursorBuffered):
            query = "select roblox_id, phrase, created from active_phrases where discord_id=%s"
            cur.execute(query, (discord_id, ))
            if cur.rowcount > 0:
                row = cur.fetchone()
                return ExpiringPhrase.from_row(row)
            else:
                return None
        return callback
    
    def get_expiring_phrase(self, discord_id : int) -> Optional[ExpiringPhrase]:
        if type(discord_id) != int:
            return None
        return self.connect_and_execute(self.create_get_phrase_callback(discord_id))

    def get_user_phrase(self, discord_id : int) -> Optional[ExpiringPhrase]:
        phrase = self.get_expiring_phrase(discord_id)
        if phrase:
            return phrase
        else:
            return None

    def create_user_phrase(self, discord_id : int, roblox_user : User) -> Optional[ExpiringPhrase]:
        if type(discord_id) != int or type(roblox_user) != User:
            return None
        def callback(cur : MySQLCursorBuffered):
            query = "insert into active_phrases (discord_id, roblox_id, phrase) values (%s, %s, %s) on duplicate key update roblox_id=%s, phrase=%s"
            random_phrase = self.generate_random_phrase()
            cur.execute(query, (discord_id, roblox_user.id, random_phrase, roblox_user.id, random_phrase))
            return self.create_get_phrase_callback(discord_id)(cur)
        return self.connect_and_execute(callback)

    def delete_expiring_phrase(self, discord_id : int):
        def callback(cur : MySQLCursorBuffered):
            query = "delete from active_phrases where discord_id=%s"
            cur.execute(query, (discord_id, ))
        self.connect_and_execute(callback)

    def verify_user(self, discord_id : int) -> Tuple[bool, User]:
        phrase = self.get_expiring_phrase(discord_id)
        user = self.get_user_from_roblox(phrase.roblox_id)
        success = phrase.phrase in user.description
        if success:
            self.delete_expiring_phrase(discord_id)
        return success, user

    def add_discord_to_roblox(self, discord_id : int, roblox_id : int) -> bool:
        if type(discord_id) != int or type(roblox_id) != int:
            return False
        def callback(cur : MySQLCursorBuffered):
            query = "insert into discord_lookup (discord_id, roblox_id) values (%s, %s) on duplicate key update roblox_id=%s"
            cur.execute(query, (discord_id, roblox_id, roblox_id))
        self.connect_and_execute(callback)
        return True

    def remove_discord_to_roblox(self, discord_id : int) -> bool:
        if type(discord_id) != int:
            return False
        def callback(cur : MySQLCursorBuffered):
            query = "delete from discord_lookup where discord_id=%s"
            cur.execute(query, (discord_id, ))
            return cur.rowcount > 0
        return self.connect_and_execute(callback)

    def get_roblox_from_discord(self, discord_id : int) -> Optional[int]:
        if type(discord_id) != int:
            return None
        def callback(cur : MySQLCursorBuffered):
            query = "select roblox_id from discord_lookup where discord_id=%s"
            cur.execute(query, (discord_id, ))
            if cur.rowcount > 0:
                row = cur.fetchone()
                return row[0]
            else:
                return None
        return self.connect_and_execute(callback)
    
    def get_discord_from_roblox(self, roblox_id : int) -> List[int]:
        if type(roblox_id) != int:
            return []
        def callback(cur : MySQLCursorBuffered):
            query = "select discord_id from discord_lookup where roblox_id=%s"
            cur.execute(query, (roblox_id, ))
            if cur.rowcount > 0:
                return [row[0] for row in cur.fetchall()]
            else:
                return []
        return self.connect_and_execute(callback)

    def generate_and_add_api_key(self, discord_id : int) -> Optional[str]:
        if type(discord_id) != int:
            return None
        generated_key = secrets.token_urlsafe(16)
        def callback(cur : MySQLCursorBuffered):
            query = "insert into api_keys (api_key, discord_id) values (%s, %s)"
            cur.execute(query, (generated_key, discord_id))
        self.connect_and_execute(callback)
        return generated_key

    def validate_api_key(self, api_key: str) -> bool:
        if type(api_key) != str or len(api_key) > 64:
            return False
        def callback(cur : MySQLCursorBuffered):
            query = "select discord_id from api_keys where api_key=%s"
            cur.execute(query, (api_key, ))
            return cur.rowcount > 0
        return self.connect_and_execute(callback)

    def remove_api_key_from_discord(self, discord_id : int) -> bool:
        if type(discord_id) != int:
            return False
        def callback(cur : MySQLCursorBuffered):
            query = "delete from api_keys where discord_id=%s"
            cur.execute(query, (discord_id, ))
            return cur.rowcount > 0
        return self.connect_and_execute(callback)
    