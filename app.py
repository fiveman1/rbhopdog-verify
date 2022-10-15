# app.py

from enum import IntEnum
from flask import Flask, jsonify, request, Response
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import functools
import json
from typing import Any, Dict, List, Optional, Union

from modules.exceptions import APIError, NotFoundError, TimeoutError
from modules.manager import AccountManager

app = Flask(__name__)
app.config["RATELIMIT_HEADERS_ENABLED"] = True

limiter = Limiter(
    app,
    key_func=get_remote_address,
    storage_uri="redis://localhost:6379",
    strategy="moving-window"
)

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

def create_error_response(code : int, message : Union[str, List[str]], error_code = ErrorCode.DEFAULT, result : Dict[str, Any] = {}) -> Response:
    if type(message) == str:
        message = [message]
    return jsonify(
        {
            "status": "error",
            "code": code,
            "messages": message,
            "result": result,
            "errorCode": error_code.value
        }
    ), code

def require_api_key():
    def wrapper(func):
        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            api_key = request.headers.get("api_key")
            if not api_key:
                return create_error_response(403, "An API key is required for this resource. It should be included in the headers as 'api_key'.")
            elif not manager.validate_api_key(api_key):
                return create_error_response(403, "The provided API key is not valid for accessing this resource.")
            else:
                return func(*args, **kwargs)
        return wrapped
    return wrapper

def validate_int(num) -> Optional[int]:
    try:
        return int(num)
    except:
        return None

@app.errorhandler(429)
def rate_limit_handler(_):
    return create_error_response(429, "You have exceeded the rate limit.")

@app.errorhandler(APIError)
def on_api_error(error : APIError):
    return create_error_response(500, f"An unexpected error occurred attempting to use the {error.api_name} API")

@app.errorhandler(TimeoutError)
def on_timeout_error(error : TimeoutError):
    return create_error_response(500, f"An timeout occurred attempting to use the {error.api_name} API")

def try_verify_discord_user(discord_id : int):
    roblox_id = manager.get_roblox_from_discord(discord_id)
    if roblox_id is not None:
        return create_error_response(400, "User is already verified.", ErrorCode.ALREADY_VERIFIED, { "robloxId": roblox_id } )
    
    phrase = manager.get_user_phrase(discord_id)
    if phrase:
        success, user = manager.verify_user(discord_id)
        if success:
            if manager.add_discord_to_roblox(discord_id, user.id):
                return create_ok_response( { "robloxId": user.id, "robloxUsername": user.username } )
            else:
                return create_error_response(500, "An unexpected error occurred.")
        else:
            result = { 
                "phrase": phrase.phrase,
                "expiresIn": phrase.time_to_expire,
                "robloxDescription": user.description, 
                "robloxId": user.id,
                "robloxUsername": user.username
            }
            return create_error_response(400, "User could not be verified. The verification phrase was not found in their About section.", ErrorCode.PHRASE_NOT_FOUND, result)
    else:
        return create_error_response(404, "The verification process is not active for this user. Either they did not start it, or their phrase expired.", ErrorCode.VERIFICATION_NOT_ACTIVE)

def begin_verify_discord_user(discord_id : int, roblox_id : int):
    roblox_id = validate_int(roblox_id)
    if not roblox_id or roblox_id < 1:
        return create_error_response(400, "The provided robloxId is invalid.")

    roblox_id = manager.get_roblox_from_discord(discord_id)
    if roblox_id is not None:
        return create_error_response(400, "User is already verified.", ErrorCode.ALREADY_VERIFIED, { "robloxId": roblox_id } )
    
    try:
        user = manager.get_user_from_roblox(roblox_id)
    except NotFoundError:
        return create_error_response(404, "User not found.")
    phrase = manager.create_user_phrase(discord_id, user)
    if phrase:
        return create_ok_response( { "phrase": phrase.phrase, "expiresIn": phrase.time_to_expire } )
    else:
        return create_error_response(500, "An unexpected error occurred.")

def remove_discord_user(discord_id : int):
    roblox_id = manager.get_roblox_from_discord(discord_id)
    if not roblox_id:
        return create_error_response(404, "User not found.")
    
    if manager.remove_discord_to_roblox(discord_id):
        user = manager.get_user_from_roblox(roblox_id)
        return create_ok_response( { "robloxId": user.id, "robloxUsername": user.username } )
    else:
        return create_error_response(500, "An unexpected error occurred.")

@app.route("/v1/verify/users/<int:discord_id>", methods=["GET", "POST", "DELETE"])
@require_api_key()
def verify_discord_user(discord_id : int):
    if request.method == "GET":
        roblox_id = request.args.get("robloxId")
        return begin_verify_discord_user(discord_id, roblox_id)
    elif request.method == "POST":
        return try_verify_discord_user(discord_id)
    elif request.method == "DELETE":
        return remove_discord_user(discord_id)

@app.route("/v1/users/<int:discord_id>", methods=["GET"])
@limiter.limit("3000/day;300/hour")
def discord_user(discord_id : int):
    roblox_id = manager.get_roblox_from_discord(discord_id)
    if roblox_id:
        return create_ok_response( { "robloxId": roblox_id } )
    else:
        return create_error_response(404, "User not found.")

@app.route("/v1/keys/<int:discord_id>", methods=["GET", "DELETE"])
def manage_api_keys(discord_id : int):
    api_key = request.headers.get("api_key")
    if api_key != OWNER_KEY:
        return create_error_response(403, "The provided API key is not valid for accessing this resource.")
    
    if request.method == "GET":
        new_key = manager.generate_and_add_api_key(discord_id)
        if new_key:
            return create_ok_response( { "apiKey": new_key } )
        else:
            return create_error_response(500, "An unexpected error occurred.")
    elif request.method == "DELETE":
        keys = manager.remove_api_key_from_discord(discord_id)
        if keys:
            return create_ok_response()
        else:
            return create_error_response(404, "No keys found to delete.")

@app.route("/")
def show_docs():
    return app.send_static_file("redoc-static.html")
