# database.py

# Run this file to setup the database for the first time
import mysql.connector as mysql
import json

def create_database(user, password):
    query = "create database discord_to_roblox"

    with mysql.connect(
        host="127.0.0.1",
        user=user,
        password=password,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(query)

def create_tables(user, password):
    create_lookup = """
        create table discord_lookup (
            discord_id bigint unsigned not null,
            roblox_id bigint unsigned not null,
            index roblox_id_idx (roblox_id),
            primary key (discord_id)
        )
        """

    create_keys = """
        create table api_keys (
            api_key varchar(64) not null,
            discord_id bigint unsigned not null,
            primary key (api_key)
        )
        """

    create_phrases = """
        create table active_phrases (
            discord_id bigint unsigned not null,
            roblox_id bigint unsigned not null,
            phrase varchar(256) not null,
            created timestamp default current_timestamp on update current_timestamp not null,
            primary key (discord_id)
        )
    """

    with mysql.connect(
        host="127.0.0.1",
        user=user,
        password=password,
        database="discord_to_roblox"
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(create_lookup)
            cur.execute(create_keys)
            cur.execute(create_phrases)

def main():

    with open("files/config.json") as file:
        config = json.load(file)
    SQL_USER = config["SQL_USER"]
    SQL_PASS = config["SQL_PASS"]

    create_database(SQL_USER, SQL_PASS)
    create_tables(SQL_USER, SQL_PASS)

if __name__ == "__main__":
    main()
