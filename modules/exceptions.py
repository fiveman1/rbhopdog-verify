# exceptions.py

class APIError(Exception):

    def __init__(self, api_name : str):
        self.api_name = api_name

class TimeoutError(Exception):
    
    def __init__(self, api_name : str):
        self.api_name = api_name

class NotFoundError(Exception):
    pass

