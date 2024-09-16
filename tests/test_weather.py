# test_freeweather.py

import pytest
import asyncio
from weather.weather import (
    GeocodingClient,
    OpenMeteoClient,
    WeatherService,
    WeatherAPIError,
    APIConnectionError,
    DataParsingError
)

@pytest.mark.asyncio
async def test_geocoding_client_success():
    geocoding_client = GeocodingClient(timeout=5)
    coordinates = await geocoding_client.get_coordinates("London")
    assert "latitude" in coordinates
    assert "longitude" in coordinates

@pytest.mark.asyncio
async def test_geocoding_client_no_results():
    geocoding_client = GeocodingClient(timeout=5)
    with pytest.raises(WeatherAPIError):
        await geocoding_client.get_coordinates("NonExistentCityXYZ")

@pytest.mark.asyncio
async def test_openmeteo_client_current_weather():
    # Replace with valid coordinates or mock the response
    client = OpenMeteoClient(latitude=51.5074, longitude=-0.1278, timeout=5)
    current_weather = await client.get_current_weather()
    assert current_weather is not None
    assert "temperature" in current_weather

@pytest.mark.asyncio
async def test_weather_service_fetch_current_weather():
    # Mocking would be ideal here, but for demonstration, using real API
    geocoding_client = GeocodingClient(timeout=5)
    coordinates = await geocoding_client.get_coordinates("London")
    client = OpenMeteoClient(latitude=coordinates['latitude'], longitude=coordinates['longitude'], timeout=5)
    service = WeatherService(client=client, cache_enabled=False)
    current_weather = await service.fetch_current_weather()
    assert "error" not in current_weather  # Ensure no error was returned
    assert "temperature" in current_weather
    assert "time" in current_weather
    assert "weathercode" in current_weather

@pytest.mark.asyncio
async def test_weather_service_fetch_forecast_invalid_days():
    geocoding_client = GeocodingClient(timeout=5)
    coordinates = await geocoding_client.get_coordinates("London")
    client = OpenMeteoClient(latitude=coordinates['latitude'], longitude=coordinates['longitude'], timeout=5)
    service = WeatherService(client=client, cache_enabled=False)
    forecast = await service.fetch_forecast(days=20)  # Invalid days
    assert "error" in forecast
    assert "Days parameter must be between 1 and 16." in forecast["error"]
