import re

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/cep", tags=["cep"])


@router.get("/{cep}")
async def consultar_cep(cep: str):
    cep_limpo = re.sub(r"\D", "", cep)

    if len(cep_limpo) != 8:
        raise HTTPException(
            status_code=422,
            detail="CEP inválido. Informe apenas os 8 dígitos.",
        )

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"https://viacep.com.br/ws/{cep_limpo}/json/")
            data = resp.json()
        except Exception:
            raise HTTPException(status_code=503, detail="Serviço de CEP indisponível.")

    if "erro" in data:
        raise HTTPException(status_code=404, detail="CEP não encontrado.")

    return {
        "cep": data.get("cep", cep_limpo),
        "rua": data.get("logradouro", ""),
        "bairro": data.get("bairro", ""),
        "cidade": data.get("localidade", ""),
        "estado": data.get("uf", ""),
    }
