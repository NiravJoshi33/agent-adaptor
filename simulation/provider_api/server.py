"""Provider's Weather API — wraps wttr.in as a monetizable service.

This is the provider's existing API that they want to expose to agent economies.
The Agent Adapter will ingest this OpenAPI spec and turn it into capabilities.

Run: uvicorn simulation.provider_api.server:app --port 8001
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="WeatherPro API",
    description="Professional weather data service. Provides current conditions and forecasts.",
    version="1.0.0",
)


class WeatherResponse(BaseModel):
    location: str
    temperature_c: float
    condition: str
    humidity: str
    wind: str


class ForecastDay(BaseModel):
    date: str
    max_temp_c: float
    min_temp_c: float
    condition: str


class ForecastResponse(BaseModel):
    location: str
    days: list[ForecastDay]


class LocationLookupResponse(BaseModel):
    query: str
    matched_location: str
    country: str
    region: str


@app.get(
    "/weather/current",
    response_model=WeatherResponse,
    operation_id="get_current_weather",
    summary="Get current weather conditions for a location",
)
async def get_current_weather(location: str) -> WeatherResponse:
    """Returns current temperature, conditions, humidity, and wind for the given location."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://wttr.in/{location}",
            params={"format": "j1"},
            headers={"User-Agent": "weatherpro-api"},
        )
        if resp.status_code != 200:
            raise HTTPException(502, "Upstream weather service unavailable")
        data = resp.json()

    current = data["current_condition"][0]
    area = data["nearest_area"][0]
    loc_name = area["areaName"][0]["value"]

    return WeatherResponse(
        location=loc_name,
        temperature_c=float(current["temp_C"]),
        condition=current["weatherDesc"][0]["value"],
        humidity=current["humidity"],
        wind=f"{current['windspeedKmph']} km/h {current['winddir16Point']}",
    )


@app.get(
    "/weather/forecast",
    response_model=ForecastResponse,
    operation_id="get_weather_forecast",
    summary="Get 3-day weather forecast for a location",
)
async def get_weather_forecast(location: str) -> ForecastResponse:
    """Returns a 3-day forecast with daily high/low temperatures and conditions."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://wttr.in/{location}",
            params={"format": "j1"},
            headers={"User-Agent": "weatherpro-api"},
        )
        if resp.status_code != 200:
            raise HTTPException(502, "Upstream weather service unavailable")
        data = resp.json()

    area = data["nearest_area"][0]
    loc_name = area["areaName"][0]["value"]
    days = []
    for day in data.get("weather", []):
        days.append(
            ForecastDay(
                date=day["date"],
                max_temp_c=float(day["maxtempC"]),
                min_temp_c=float(day["mintempC"]),
                condition=day["hourly"][4]["weatherDesc"][0]["value"],
            )
        )

    return ForecastResponse(location=loc_name, days=days)


@app.get(
    "/weather/lookup",
    response_model=LocationLookupResponse,
    operation_id="lookup_location",
    summary="Look up a location and return its canonical name",
)
async def lookup_location(query: str) -> LocationLookupResponse:
    """Resolves a location query to its canonical name, country, and region."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://wttr.in/{query}",
            params={"format": "j1"},
            headers={"User-Agent": "weatherpro-api"},
        )
        if resp.status_code != 200:
            raise HTTPException(502, "Upstream weather service unavailable")
        data = resp.json()

    area = data["nearest_area"][0]
    return LocationLookupResponse(
        query=query,
        matched_location=area["areaName"][0]["value"],
        country=area["country"][0]["value"],
        region=area["region"][0]["value"],
    )
