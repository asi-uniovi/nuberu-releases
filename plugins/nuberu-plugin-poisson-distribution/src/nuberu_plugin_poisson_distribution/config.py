from typing import Literal, Union, Annotated
from pydantic import BaseModel, Field, TypeAdapter


class PoissonByReqsAndTime(BaseModel):
    mode: Literal["by_num_reqs_and_time"]
    num_reqs: int = Field(..., gt=0, description="Number of requests to generate")
    time_slot_size: float = Field(
        ..., gt=0, description="Total time in seconds over which to generate requests"
    )


class PoissonByRateAndNumReqs(BaseModel):
    mode: Literal["by_rate_and_num_reqs"]
    rate: float = Field(..., gt=0, description="Rate of requests per second")
    num_reqs: int = Field(..., gt=0, description="Number of requests to generate")


class PoissonByRateAndTime(BaseModel):
    mode: Literal["by_rate_and_time"]
    rate: float = Field(..., gt=0, description="Rate of requests per second")
    total_time: float = Field(
        ..., gt=0, description="Total time in seconds over which to generate requests"
    )


class PoissonByRateOnly(BaseModel):
    mode: Literal["by_rate"]
    rate: float = Field(..., gt=0, description="Rate of requests per second")


PoissonConfig = Annotated[
    Union[
        PoissonByRateAndNumReqs,
        PoissonByRateAndTime,
        PoissonByReqsAndTime,
        PoissonByRateOnly,
    ],
    Field(
        discriminator="mode",
        description="Mode of operation for the Poisson distribution configuration",
    ),
]

ConfigValidator = TypeAdapter(PoissonConfig)


def generate_json_schema():
    """
    Generates a JSON schema for the AnyPoissonConfig model.
    This function is useful for generating documentation or validation schemas.
    """
    from pydantic import RootModel
    import json

    class SchemaGen(RootModel[PoissonConfig]):
        pass

    schema = SchemaGen.model_json_schema()
    return json.dumps(schema, indent=2)


if __name__ == "__main__":
    # Example usage
    print(generate_json_schema())
