### Description

This API verifies Discord users to Roblox users. This allows one to link their Discord account to their Roblox account.
You can then retrieve verified accounts via the API.

### Response Structure

Every response has the following:
Attribute | Description
---|---
code | The status code
errorCode | A custom error code (refer to table below)
messages | If there is an error, this is a list of messages describing what went wrong
result | This contains data based on the request
status | Either "ok" or "error"

### API Keys

To retrieve users from the API via GET /v1/users/{discordId}, no API key is required.
The other endpoints require an API key.

### Error Codes

`errorCode` is included in every response. It is an integer corresponding to an enum:


Value | Title | Description
------|--------|------------
 0 | None | No error occurred.
 1 | Default | An error occurred. This is a catch all.
 2 | Already Verified | Tried to verify a user that was already verified.
 3 | Phrase Not Found | Could not verify a user because their verification phrase was missing.
 4 | Verification Inactive | Could not verify a user because they do not have verification active.
