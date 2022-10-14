# verifier.py

import aiohttp
import aiomysql
import asyncio
import random
import secrets
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from modules.exceptions import TimeoutError, NotFoundError, APIError

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

    def __init__(self, time : float, phrase : str, roblox_id : int, seconds_to_expire : float):
        self.time = time
        self.phrase = phrase
        self.roblox_id = roblox_id
        self.seconds_to_expire = seconds_to_expire

    def time_to_expire(self) -> float:
        return self.seconds_to_expire - (time.monotonic() - self.time)

    def is_expired(self) -> bool:
        return self.time_to_expire() <= 0.0

    def __bool__(self) -> bool:
        return not self.is_expired()

class AccountManager:

    def __init__(self, user, password):
        self.user = user
        self.password = password
        self.id_to_phrase : Dict[int, ExpiringPhrase] = {}
        with open("files/words.txt") as file:
            self.words = file.read().split(",")

    async def get_request(self, url : str, name : str, callback : Callable[[aiohttp.ClientResponse], Awaitable[Any]]) -> Any:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(url) as res:
                    if res.status == 404:
                        raise NotFoundError
                    elif res.status < 200 or res.status >= 300:
                        raise APIError(name)
                    else:
                        return await callback(res)
        except asyncio.TimeoutError:
            raise TimeoutError(name)

    async def get_user_from_roblox(self, user_id : int) -> User:
        async def callback(res : aiohttp.ClientResponse):
            return User.from_dict(await res.json())
        return await self.get_request(f"https://users.roblox.com/v1/users/{user_id}", "Roblox Users", callback)
        
    def generate_random_phrase(self) -> str:
        return " ".join(random.sample(self.words, 20))

    def get_expiring_phrase(self, discord_id : int) -> Optional[ExpiringPhrase]:
        return self.id_to_phrase.get(discord_id)

    def get_user_phrase(self, discord_id : int) -> Optional[ExpiringPhrase]:
        phrase = self.get_expiring_phrase(discord_id)
        if phrase:
            return phrase
        else:
            return None

    def create_user_phrase(self, discord_id : int, roblox_user : User) -> ExpiringPhrase:
        phrase = ExpiringPhrase(time.monotonic(), self.generate_random_phrase(), roblox_user.id, 15*60)
        self.id_to_phrase[discord_id] = phrase
        return phrase

    async def verify_user(self, discord_id : int) -> Tuple[bool, User]:
        phrase = self.get_expiring_phrase(discord_id)
        user = await self.get_user_from_roblox(phrase.roblox_id)
        # check that the id hasn't been removed already due to concurrency
        success = (discord_id in self.id_to_phrase) and (phrase.phrase in user.description)
        if success:
            del self.id_to_phrase[discord_id]
        return success, user

    async def connect_and_execute(self, callback : Callable[[aiomysql.Cursor], Awaitable[Any]]) -> Any:
        pool = await aiomysql.create_pool(
                host="127.0.0.1", port=3306, user=self.user, 
                password=self.password, db="discord_to_roblox", autocommit=True
            )
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                return await callback(cur)

    async def add_discord_to_roblox(self, discord_id : int, roblox_id : int) -> bool:
        if type(discord_id) != int or type(roblox_id) != int:
            return False
        async def callback(cur : aiomysql.Cursor):
            query = "insert into discord_lookup (discord_id, roblox_id) values (%s, %s) on duplicate key update roblox_id=%s"
            rows = await cur.execute(query, (discord_id, roblox_id, roblox_id))
            return rows > 0
        return await self.connect_and_execute(callback)

    async def remove_discord_to_roblox(self, discord_id : int) -> bool:
        if type(discord_id) != int:
            return False
        async def callback(cur : aiomysql.Cursor):
            query = "delete from discord_lookup where discord_id=%s"
            rows = await cur.execute(query, (discord_id, ))
            return rows > 0
        return await self.connect_and_execute(callback)

    async def get_roblox_from_discord(self, discord_id : int) -> Optional[int]:
        if type(discord_id) != int:
            return None
        async def callback(cur : aiomysql.Cursor):
            query = "select roblox_id from discord_lookup where discord_id=%s"
            rows = await cur.execute(query, (discord_id, ))
            if rows <= 0:
                return None
            (roblox_id, ) = await cur.fetchone()
            return roblox_id
        return await self.connect_and_execute(callback)

    async def generate_and_add_api_key(self, discord_id : int) -> Optional[str]:
        if type(discord_id) != int:
            return None
        generated_key = secrets.token_urlsafe(16)
        async def callback(cur : aiomysql.Cursor):
            query = "insert into api_keys (api_key, discord_id) values (%s, %s)"
            rows = await cur.execute(query, (generated_key, discord_id))
            return rows > 0
        if not await self.connect_and_execute(callback):
            return None
        return generated_key

    async def validate_api_key(self, api_key: str) -> bool:
        if type(api_key) != str or len(api_key) > 64:
            return False
        async def callback(cur : aiomysql.Cursor):
            query = "select discord_id from api_keys where api_key=%s"
            rows = await cur.execute(query, (api_key, ))
            return rows > 0
        return await self.connect_and_execute(callback)

    async def remove_api_key_from_discord(self, discord_id : int) -> bool:
        if type(discord_id) != int:
            return False
        async def callback(cur : aiomysql.Cursor):
            query = "delete from api_keys where discord_id=%s"
            rows = await cur.execute(query, (discord_id, ))
            return rows > 0
        return await self.connect_and_execute(callback)
    