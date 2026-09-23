#import pyodbc
import functools
#from api_susar.api_utilities import CONNECTION_STRING, API_KEY, PATH_APPLICATION_CONFIGURATION_ENDPOINT, API_FICHA, ENV, MOCK_FICHA
from flask import jsonify, make_response, request
import requests
import logging

logger = logging.getLogger('logger')

"""
def connectionWrapper(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            conn = pyodbc.connect(CONNECTION_STRING)
            cur = conn.cursor()
            return func(cur, conn, *args, **kwargs)
        except Exception as e:
            # log with logger module
            logger.error(f"Error connecting to database: {e}")

            return make_response(
                jsonify({"message": f"Error connecting to database: {e}"}), 500
            )
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass  # Ignore errors closing the connection, the actual error was already handled

    return wrapper


def apiKeyWrapper(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            api_key = request.headers.get("x-api-key", request.headers.get("X-Api-Key"))
            if api_key != API_KEY:
                return make_response(jsonify({"message": "Invalid API key"}), 401)
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error validating API key: {e}")
            return make_response(
                jsonify({"message": f"Error validating API key: {e}"}), 500
            )

    return wrapper


def permValidator(perm_key = None):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                if MOCK_FICHA:
                    return func(*args, **kwargs)
                access_token = request.headers.get("Authorization")
                if 'Bearer ' in access_token:
                    access_token = access_token.split('Bearer ')[1]
                if not access_token:
                    return make_response(jsonify({"message": "No access token found"}), 401)
                response = requests.get(
                    f"{API_FICHA}{PATH_APPLICATION_CONFIGURATION_ENDPOINT}",
                    headers={"Authorization": f"Bearer {access_token}"},
                    verify= True if ENV != "LOCALHOST" else False
                )
                if response.json().get("currentUser").get("isAuthenticated"):
                    if not perm_key:
                        return func(*args, **kwargs)
                    if response.json().get("auth").get("grantedPolicies").get(perm_key):
                        return func(*args, **kwargs)
                    else:
                        return make_response(
                            jsonify({"message": "User does not have the required permissions."}), 403
                        )
                else:
                    return make_response(jsonify({"message": "Not authenticated"}), 401)
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                return make_response(
                    jsonify({"message": f"Unexpected error: {e}"}), 500
                )
        return wrapper
    return decorator

"""