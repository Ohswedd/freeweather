# freeweather.py

import json
import httpx
from datetime import datetime, timedelta, timezone
import time
from typing import Optional, Dict, Any, List, Callable, Tuple, Union
from abc import ABC, abstractmethod
from pydantic import BaseModel, Field, ValidationError
import logging
import asyncio
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)

# ------------------- Exceptions -------------------


class WeatherAPIError(Exception):
    """Base exception for Weather API errors."""
    pass


class InvalidParameterError(WeatherAPIError):
    """Exception raised for invalid input parameters."""
    pass


class APIConnectionError(WeatherAPIError):
    """Exception raised for network-related errors."""
    pass


class DataParsingError(WeatherAPIError):
    """Exception raised when parsing API response fails."""
    pass

# ------------------- Interfaces -------------------


class IWeatherClient(ABC):
    """Interface for weather API clients."""

    @abstractmethod
    async def get_current_weather(self) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_forecast(self, days: int = 7) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_historical_weather(self, start_date: str, end_date: str) -> Optional[Dict[str, Any]]:
        pass

# ------------------- Models -------------------


class CurrentWeather(BaseModel):
    temperature: float = Field(..., alias='temperature')
    windspeed: float = Field(..., alias='windspeed')
    winddirection: float = Field(..., alias='winddirection')
    weathercode: int = Field(..., alias='weathercode')
    time: str = Field(..., alias='time')


class DailyForecast(BaseModel):
    time: List[str]
    temperature_2m_max: List[Optional[float]]
    temperature_2m_min: List[Optional[float]]
    precipitation_sum: List[Optional[float]]
    windspeed_10m_max: List[Optional[float]]
    weathercode: List[Optional[int]]


class HistoricalWeather(DailyForecast):
    pass


class WeatherData(BaseModel):
    current: Optional[CurrentWeather]
    forecast: Optional[DailyForecast]
    historical: Optional[HistoricalWeather]

# ------------------- Utilities -------------------

WEATHER_CODES: Dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail"
}


def get_weather_description(code: Optional[int]) -> str:
    """
    Translate a weather code into a human-readable description.

    Args:
        code (Optional[int]): The weather code.

    Returns:
        str: Description of the weather.
    """
    if code is None:
        return "Unknown"
    return WEATHER_CODES.get(code, "Unknown")

# ------------------- Caching Decorator -------------------


class TTLCacheDecorator:
    """
    A simple thread-safe TTL (Time-To-Live) cache decorator for asynchronous functions.
    Caches the result of the function call based on its arguments for a specified TTL.
    """

    def __init__(self, ttl: int = 300):
        """
        Initialize the cache decorator.

        Args:
            ttl (int): Time-to-live for cache entries in seconds.
        """
        self.ttl = ttl
        self.cache: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        self.lock = asyncio.Lock()
        self.logger = logging.getLogger(self.__class__.__name__)

    def __call__(self, func: Callable):
        """
        Decorate an asynchronous function with caching.

        Args:
            func (Callable): The asynchronous function to decorate.

        Returns:
            Callable: The wrapped function with caching.
        """
        async def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            current_time = time.time()
            async with self.lock:
                if key in self.cache:
                    entry = self.cache[key]
                    if current_time < entry['expiry']:
                        self.logger.debug(f"Cache hit for {func.__name__} with args {args} {kwargs}")
                        return entry['value']
                    else:
                        self.logger.debug(f"Cache expired for {func.__name__} with args {args} {kwargs}")
                        del self.cache[key]
                # Cache miss; call the function
                self.logger.debug(f"Cache miss for {func.__name__} with args {args} {kwargs}")
                result = await func(*args, **kwargs)
                self.cache[key] = {
                    'value': result,
                    'expiry': current_time + self.ttl
                }
                self.logger.debug(f"Cache set for {func.__name__} with args {args} {kwargs}")
                return result
        return wrapper

# ------------------- Configuration -------------------


class Settings:
    """
    Configuration settings for FreeWeather.

    Attributes:
        latitude (Optional[float]): Latitude of the location.
        longitude (Optional[float]): Longitude of the location.
        timeout (int): Timeout for HTTP requests in seconds.
        cache_enabled (bool): Whether caching is enabled.
        cache_ttl (int): Time-to-live for cache entries in seconds.
    """

    def __init__(self,
                 latitude: Optional[float] = None,
                 longitude: Optional[float] = None,
                 timeout: int = 10,
                 cache_enabled: bool = False,
                 cache_ttl: int = 300):
        self.latitude = latitude
        self.longitude = longitude
        self.timeout = timeout
        self.cache_enabled = cache_enabled
        self.cache_ttl = cache_ttl

# ------------------- Geocoding Client -------------------


class GeocodingClient:
    """
    Client to interact with the Open-Meteo Geocoding API.

    Args:
        timeout (int): Timeout for HTTP requests in seconds.
    """

    def __init__(self, timeout: int = 10):
        self.base_url = "https://geocoding-api.open-meteo.com/v1/search"
        self.timeout = timeout
        self.logger = logging.getLogger(self.__class__.__name__)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((APIConnectionError, httpx.RequestError)),
        before_sleep=before_sleep_log(logging.getLogger("freeweather.GeocodingClient"), logging.WARNING)
    )
    async def get_coordinates(self, city: str) -> Dict[str, Any]:
        """
        Retrieve latitude and longitude for a given city name.

        Args:
            city (str): Name of the city.

        Returns:
            Dict[str, Any]: Dictionary containing 'latitude' and 'longitude'.

        Raises:
            WeatherAPIError: If no results are found.
            APIConnectionError: If there's a network-related error.
            DataParsingError: If response parsing fails.
        """
        params = {
            "name": city,
            "count": 1,  # Retrieve the top result
            "language": "en",
            "format": "json"
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                self.logger.debug(f"Requesting coordinates for city '{city}' with params: {params}")
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
                data = response.json()
                self.logger.debug(f"Geocoding data received: {data}")
                results = data.get("results")
                if results:
                    top_result = results[0]
                    return {
                        "latitude": top_result.get("latitude"),
                        "longitude": top_result.get("longitude")
                    }
                else:
                    self.logger.error(f"No geocoding results found for city '{city}'.")
                    raise WeatherAPIError(f"No geocoding results found for city '{city}'.")
            except httpx.RequestError as e:
                self.logger.error(f"Error fetching geocoding data: {e}")
                raise APIConnectionError(f"Failed to fetch geocoding data: {e}")
            except ValueError as e:
                self.logger.error(f"Error parsing geocoding data: {e}")
                raise DataParsingError(f"Failed to parse geocoding data: {e}")

# ------------------- API Client -------------------


class OpenMeteoClient(IWeatherClient):
    """
    Client to interact with the Open-Meteo API.

    Args:
        latitude (float): Latitude of the location.
        longitude (float): Longitude of the location.
        timeout (int): Timeout for HTTP requests in seconds.
    """

    def __init__(self, latitude: float, longitude: float, timeout: int = 10):
        self.latitude = latitude
        self.longitude = longitude
        self.timeout = timeout
        self.base_url_forecast = "https://api.open-meteo.com/v1"
        self.base_url_archive = "https://archive-api.open-meteo.com/v1"
        self.logger = logging.getLogger(self.__class__.__name__)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((APIConnectionError, httpx.RequestError)),
        before_sleep=before_sleep_log(logging.getLogger("freeweather.OpenMeteoClient"), logging.WARNING)
    )
    async def get_current_weather(self) -> Optional[Dict[str, Any]]:
        """
        Fetch current weather data.

        Returns:
            Optional[Dict[str, Any]]: Current weather data.

        Raises:
            APIConnectionError: If there's a network-related error.
            DataParsingError: If response parsing fails.
        """
        endpoint = f"{self.base_url_forecast}/forecast"
        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "current_weather": True,
            "timezone": "auto"
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                self.logger.debug(f"Requesting current weather with params: {params}")
                response = await client.get(endpoint, params=params)
                response.raise_for_status()
                data = response.json()
                self.logger.debug(f"Current weather data received: {data}")
                return data.get("current_weather")
            except httpx.RequestError as e:
                self.logger.error(f"Error fetching current weather: {e}")
                raise APIConnectionError(f"Failed to fetch current weather: {e}")
            except ValueError as e:
                self.logger.error(f"Error parsing current weather data: {e}")
                raise DataParsingError(f"Failed to parse current weather data: {e}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((APIConnectionError, httpx.RequestError)),
        before_sleep=before_sleep_log(logging.getLogger("freeweather.OpenMeteoClient"), logging.WARNING)
    )
    async def get_forecast(self, days: int = 7) -> Optional[Dict[str, Any]]:
        """
        Fetch weather forecast data.

        Args:
            days (int): Number of days for the forecast (1-16).

        Returns:
            Optional[Dict[str, Any]]: Forecast data.

        Raises:
            InvalidParameterError: If 'days' is out of allowed range.
            APIConnectionError: If there's a network-related error.
            DataParsingError: If response parsing fails.
        """
        if not (1 <= days <= 16):
            self.logger.error("Days parameter must be between 1 and 16.")
            raise InvalidParameterError("Days parameter must be between 1 and 16.")

        endpoint = f"{self.base_url_forecast}/forecast"
        end_date = datetime.now(timezone.utc) + timedelta(days=days)
        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "daily": [
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "windspeed_10m_max",
                "windgusts_10m_max",
                "weathercode"
            ],
            "timezone": "auto",
            "start_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d")
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                self.logger.debug(f"Requesting forecast with params: {params}")
                response = await client.get(endpoint, params=params)
                response.raise_for_status()
                data = response.json()
                self.logger.debug(f"Forecast data received: {data}")
                return data.get("daily")
            except httpx.RequestError as e:
                self.logger.error(f"Error fetching forecast: {e}")
                raise APIConnectionError(f"Failed to fetch forecast: {e}")
            except ValueError as e:
                self.logger.error(f"Error parsing forecast data: {e}")
                raise DataParsingError(f"Failed to parse forecast data: {e}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((APIConnectionError, httpx.RequestError)),
        before_sleep=before_sleep_log(logging.getLogger("freeweather.OpenMeteoClient"), logging.WARNING)
    )
    async def get_historical_weather(self, start_date: str, end_date: str) -> Optional[Dict[str, Any]]:
        """
        Fetch historical weather data.

        Args:
            start_date (str): Start date in 'YYYY-MM-DD' format.
            end_date (str): End date in 'YYYY-MM-DD' format.

        Returns:
            Optional[Dict[str, Any]]: Historical weather data.

        Raises:
            APIConnectionError: If there's a network-related error.
            DataParsingError: If response parsing fails.
        """
        endpoint = f"{self.base_url_archive}/archive"
        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "start_date": start_date,
            "end_date": end_date,
            "daily": [
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "windspeed_10m_max",
                "weathercode"
            ],
            "timezone": "auto"
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                self.logger.debug(f"Requesting historical weather with params: {params}")
                response = await client.get(endpoint, params=params)
                response.raise_for_status()
                data = response.json()
                self.logger.debug(f"Historical weather data received: {data}")
                return data.get("daily")
            except httpx.RequestError as e:
                self.logger.error(f"Error fetching historical weather: {e}")
                raise APIConnectionError(f"Failed to fetch historical weather: {e}")
            except ValueError as e:
                self.logger.error(f"Error parsing historical weather data: {e}")
                raise DataParsingError(f"Failed to parse historical weather data: {e}")

# ------------------- Weather Service -------------------


class WeatherService:
    """
    Service to manage weather data retrieval and processing.

    Args:
        client (IWeatherClient): The weather API client.
        cache_enabled (bool): Whether caching is enabled.
        cache_ttl (int): Time-to-live for cache entries in seconds.
    """

    def __init__(self, client: IWeatherClient, cache_enabled: bool = False, cache_ttl: int = 300):
        self.client = client
        self.logger = logging.getLogger(self.__class__.__name__)
        self.cache_enabled = cache_enabled
        self.cache_ttl = cache_ttl
        if self.cache_enabled:
            self.current_weather_cache = TTLCacheDecorator(ttl=self.cache_ttl)
            self.forecast_cache = TTLCacheDecorator(ttl=self.cache_ttl)
            self.historical_weather_cache = TTLCacheDecorator(ttl=self.cache_ttl)
            self.logger.debug("Caching is enabled.")
        else:
            # If caching is disabled, use identity functions
            self.current_weather_cache = lambda func: func
            self.forecast_cache = lambda func: func
            self.historical_weather_cache = lambda func: func
            self.logger.debug("Caching is disabled.")

    async def fetch_current_weather(self) -> Union[Dict[str, Any], Dict[str, str]]:
        """
        Fetch and return current weather data.

        Returns:
            Union[Dict[str, Any], Dict[str, str]]: Current weather data or error message.
        """
        try:
            if self.cache_enabled:
                # Apply caching decorator
                data = await self.current_weather_cache(self.client.get_current_weather)()
            else:
                # Directly fetch without caching
                data = await self.client.get_current_weather()
            if not data:
                self.logger.error("No current weather data received.")
                raise WeatherAPIError("No current weather data received.")
            current_weather = CurrentWeather(**data)
            self.logger.debug(f"Parsed current weather: {current_weather}")
            return current_weather.model_dump()
        except ValidationError as e:
            self.logger.error(f"Data validation error: {e}")
            return {"error": f"Data validation error: {e}"}
        except WeatherAPIError as e:
            self.logger.error(f"Weather API error: {e}")
            return {"error": str(e)}

    async def fetch_forecast(self, days: int = 7) -> Union[Dict[str, Any], Dict[str, str]]:
        """
        Fetch and return weather forecast data.

        Args:
            days (int): Number of days for the forecast (1-16).

        Returns:
            Union[Dict[str, Any], Dict[str, str]]: Forecast data or error message.
        """
        try:
            if self.cache_enabled:
                # Apply caching decorator
                data = await self.forecast_cache(lambda: self.client.get_forecast(days=days))()
            else:
                # Directly fetch without caching
                data = await self.client.get_forecast(days=days)
            if not data:
                self.logger.error("No forecast data received.")
                raise WeatherAPIError("No forecast data received.")
            forecast = DailyForecast(**data)
            self.logger.debug(f"Parsed forecast data: {forecast}")
            return forecast.model_dump()
        except ValidationError as e:
            self.logger.error(f"Data validation error: {e}")
            return {"error": f"Data validation error: {e}"}
        except WeatherAPIError as e:
            self.logger.error(f"Weather API error: {e}")
            return {"error": str(e)}

    async def fetch_historical_weather(self, start_date: str, end_date: str) -> Union[Dict[str, Any], Dict[str, str]]:
        """
        Fetch and return historical weather data.

        Args:
            start_date (str): Start date in 'YYYY-MM-DD' format.
            end_date (str): End date in 'YYYY-MM-DD' format.

        Returns:
            Union[Dict[str, Any], Dict[str, str]]: Historical weather data or error message.
        """
        try:
            if self.cache_enabled:
                # Apply caching decorator
                data = await self.historical_weather_cache(lambda: self.client.get_historical_weather(start_date, end_date))()
            else:
                # Directly fetch without caching
                data = await self.client.get_historical_weather(start_date, end_date)
            if not data:
                self.logger.error("No historical weather data received.")
                raise WeatherAPIError("No historical weather data received.")
            historical = HistoricalWeather(**data)
            self.logger.debug(f"Parsed historical weather data: {historical}")
            return historical.model_dump()
        except ValidationError as e:
            self.logger.error(f"Data validation error: {e}")
            return {"error": f"Data validation error: {e}"}
        except WeatherAPIError as e:
            self.logger.error(f"Weather API error: {e}")
            return {"error": str(e)}
