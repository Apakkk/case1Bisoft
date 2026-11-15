"""API DTOs for city suggestions."""

from pydantic import BaseModel, Field

from app.models.city import CitySource, CitySuggestion, CitySuggestions


class CitySuggestionOut(BaseModel):
    name: str = Field(examples=["Orlando"])
    state: str = Field(examples=["FL"], description="Two-letter US state code ('' if unknown)")
    source: CitySource = Field(description="catalog = shipped list; ors = found via OpenRouteService")

    @classmethod
    def from_suggestion(cls, suggestion: CitySuggestion) -> "CitySuggestionOut":
        return cls(name=suggestion.name, state=suggestion.state, source=suggestion.source)


class CitySuggestionsOut(BaseModel):
    items: list[CitySuggestionOut]
    warnings: list[str] = Field(description="Turkish notes, e.g. the map service could not be reached")

    @classmethod
    def from_suggestions(cls, result: CitySuggestions) -> "CitySuggestionsOut":
        return cls(items=[CitySuggestionOut.from_suggestion(s) for s in result.items], warnings=list(result.warnings))
