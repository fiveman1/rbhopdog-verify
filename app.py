# app.py

import asyncio
from enum import IntEnum
from flask import Flask, jsonify, request, Response
import functools
import json
from typing import Any, Dict, List, Optional

from modules.exceptions import NotFoundError
from modules.manager import AccountManager, User

app = Flask(__name__)

with open("files/config.json") as file:
    config = json.load(file)

manager = AccountManager(config["USER"], config["PASS"])
OWNER_KEY = config["API_KEY"]

class ErrorCode(IntEnum):
    NONE = 0
    DEFAULT = 1
    ALREADY_VERIFIED = 2
    PHRASE_NOT_FOUND = 3
    VERIFICATION_NOT_ACTIVE = 4

def create_ok_response(result : Dict[str, Any] = {}) -> Response:
    return jsonify(
        {
            "status": "ok",
            "code": 200,
            "messages": [],
            "result": result,
            "errorCode": ErrorCode.NONE.value
        }
    )

def create_error_response(code : int, messages : List[str], error_code = ErrorCode.DEFAULT, result : Dict[str, Any] = {}) -> Response:
    return jsonify(
        {
            "status": "error",
            "code": code,
            "messages": messages,
            "result": result,
            "errorCode": error_code.value
        }
    ), code

def require_api_key():
    def wrapper(func):
        @functools.wraps(func)
        async def wrapped(*args, **kwargs):
            api_key = request.headers.get("api_key")
            if not api_key:
                return create_error_response(403, ["An API key is required for this resource. It should be included in the headers as 'api_key'."])
            elif not await manager.validate_api_key(api_key):
                return create_error_response(403, ["The provided API key is not valid for accessing this resource."])
            else:
                return await func(*args, **kwargs)
        return wrapped
    return wrapper

def validate_int(num) -> Optional[int]:
    try:
        return int(num)
    except ValueError:
        return None

async def try_verify_discord_user(discord_id : int):
    if await manager.get_roblox_from_discord(discord_id) is not None:
        return create_error_response(400, ["User is already verified."], ErrorCode.ALREADY_VERIFIED)
    phrase = manager.get_user_phrase(discord_id)
    if phrase:
        success, user = await manager.verify_user(discord_id)
        if success:
            if await manager.add_discord_to_roblox(discord_id, user.id):
                return create_ok_response( { "robloxId": user.id, "robloxUsername": user.username } )
            else:
                return create_error_response(500, ["An unexpected error occurred."])
        else:
            result = { 
                "phrase": phrase.phrase,
                "expiresIn": int(phrase.time_to_expire()),
                "description": user.description, 
                "robloxId": user.id,
                "robloxUsername": user.username
            }
            return create_error_response(400, ["User could not be verified. The verification phrase was not found in their About section."], ErrorCode.PHRASE_NOT_FOUND, result)
    else:
        return create_error_response(400, ["The verification process is not active for this user. Either they did not start it, or their phrase expired."], ErrorCode.VERIFICATION_NOT_ACTIVE)

async def begin_verify_discord_user(discord_id : int, roblox_id : int):
    roblox_id = validate_int(roblox_id)
    if not roblox_id or roblox_id < 1:
        return create_error_response(400, ["The provided robloxId is invalid."])

    if await manager.get_roblox_from_discord(discord_id) is not None:
        return create_error_response(400, ["User is already verified."], ErrorCode.ALREADY_VERIFIED)
    
    try:
        user = await manager.get_user_from_roblox(roblox_id)
    except NotFoundError:
        return create_error_response(404, ["User not found."])
    phrase = manager.create_user_phrase(discord_id, user)
    return create_ok_response( { "phrase": phrase.phrase, "expiresIn": int(phrase.time_to_expire()) } )

async def get_discord_user(discord_id : int):
    roblox_id = await manager.get_roblox_from_discord(discord_id)
    if roblox_id:
        return create_ok_response( { "robloxId": roblox_id } )
    else:
        return create_error_response(404, ["User not found."])

@require_api_key()
async def verify_discord_user(discord_id : int, roblox_id : int):
    if roblox_id is None:
        return await try_verify_discord_user(discord_id)
    else:
        return await begin_verify_discord_user(discord_id, roblox_id)

@require_api_key()
async def remove_discord_user(discord_id : int):
    roblox_id = await manager.get_roblox_from_discord(discord_id)
    if not roblox_id:
        return create_error_response(404, ["User not found."])
    
    tasks = [manager.get_user_from_roblox(roblox_id), manager.remove_discord_to_roblox(discord_id)]
    results = await asyncio.gather(*tasks)
    user : User = results[0]
    success : bool = results[1]
    if success:
        return create_ok_response( { "robloxId": user.id, "robloxUsername": user.username } )
    else:
        return create_error_response(500, ["An unexpected error occurred."])

@app.route("/api/v1/users/<int:discord_id>", methods=["GET", "POST", "DELETE"])
async def discord_user(discord_id : int):
    if request.method == "GET":
        return await get_discord_user(discord_id)
    elif request.method == "POST":
        roblox_id = request.args.get("robloxId")
        return await verify_discord_user(discord_id, roblox_id)
    elif request.method == "DELETE":
        return await remove_discord_user(discord_id)

@app.route("/api/v1/keys/<int:discord_id>", methods=["GET", "DELETE"])
async def manage_api_keys(discord_id : int):
    api_key = request.headers.get("api_key")
    if api_key != OWNER_KEY:
        return create_error_response(403, ["The provided API key is not valid for accessing this resource."])
    
    if request.method == "GET":
        new_key = await manager.generate_and_add_api_key(discord_id)
        if new_key:
            return create_ok_response( { "apiKey": new_key } )
        else:
            return create_error_response(500, ["An unexpected error occurred."])
    elif request.method == "DELETE":
        keys = await manager.remove_api_key_from_discord(discord_id)
        if keys:
            return create_ok_response()
        else:
            return create_error_response(404, ["No keys found to delete."])
