from typing import Literal, Union, Annotated
from pydantic import BaseModel, Field, TypeAdapter


class TraceFromRpsTextFile(BaseModel):
    """Reads the number of rps from a simple text file, in which
    each line contains a single number representing the rate of requests per second for that second.
    """

    mode: Literal["rps_from_file"]
    rate_file_path: str = Field(
        ..., description="Path to the file containing request rates per second"
    )
    csv_offset: int = Field(
        0, ge=0, description="Line offset in the CSV file to start reading from"
    )
    injecting_end_time: float = Field(
        float("inf"),  # If not specified, the loop will run indefinitely
        gt=0,
        description="End time for injecting requests (optional, defaults to infinite loop)",
    )
    inter_arrivals: Literal["uniform", "poisson"] = Field(
        "uniform",
        description="Type of inter-arrival time distribution to use. Possible values: 'uniform' (default), 'poisson'.",
    )


TraceConfig = Annotated[
    Union[TraceFromRpsTextFile],
    Field(
        discriminator="mode",
        description="Mode of operation for the Trace distribution configuration",
    ),
]

ConfigValidator = TypeAdapter(TraceConfig)


def generate_json_schema():
    """
    Generates a JSON schema for the TraceConfig model.
    This function is useful for generating documentation or validation schemas.
    """
    import json

    schema = ConfigValidator.json_schema()
    return json.dumps(schema, indent=2)


if __name__ == "__main__":
    print(generate_json_schema())
