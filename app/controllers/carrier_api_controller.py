from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.dependencies import get_carrier_service
from app.schemas.carrier import CarrierIn, CarrierOut
from app.services.carrier_service import CarrierService

router = APIRouter(prefix="/api/v1/carriers", tags=["carriers"])

Service = Annotated[CarrierService, Depends(get_carrier_service)]


@router.get("", response_model=list[CarrierOut])
def list_carriers(service: Service) -> list[CarrierOut]:
    return [CarrierOut.from_carrier(c) for c in service.list()]


@router.post("", response_model=CarrierOut, status_code=status.HTTP_201_CREATED)
def create_carrier(data: CarrierIn, service: Service) -> CarrierOut:
    return CarrierOut.from_carrier(service.create(data))


@router.get("/{carrier_id}", response_model=CarrierOut)
def get_carrier(carrier_id: int, service: Service) -> CarrierOut:
    return CarrierOut.from_carrier(service.get(carrier_id))


@router.put("/{carrier_id}", response_model=CarrierOut)
def update_carrier(carrier_id: int, data: CarrierIn, service: Service) -> CarrierOut:
    return CarrierOut.from_carrier(service.update(carrier_id, data))


@router.delete("/{carrier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_carrier(carrier_id: int, service: Service) -> Response:
    service.delete(carrier_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
