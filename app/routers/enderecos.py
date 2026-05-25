from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.dependencies import get_current_user
from app.models.usuario import Usuario
from app.models.endereco import Endereco
from app.schemas.endereco import EnderecoCreate, EnderecoResponse

router = APIRouter(prefix="/usuario/enderecos", tags=["enderecos"])


@router.get("", response_model=List[EnderecoResponse])
def listar_enderecos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return db.query(Endereco).filter(Endereco.usuario_id == current_user.id).all()


@router.post("", response_model=EnderecoResponse, status_code=status.HTTP_201_CREATED)
def criar_endereco(
    data: EnderecoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    endereco = Endereco(
        usuario_id=current_user.id,
        apelido=data.apelido,
        cep=data.cep,
        rua=data.rua,
        numero=data.numero,
        complemento=data.complemento,
        bairro=data.bairro,
        cidade=data.cidade,
        estado=data.estado,
    )
    db.add(endereco)
    db.commit()
    db.refresh(endereco)
    return endereco


@router.put("/{endereco_id}", response_model=EnderecoResponse)
def atualizar_endereco(
    endereco_id: int,
    data: EnderecoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    endereco = db.query(Endereco).filter(
        Endereco.id == endereco_id,
        Endereco.usuario_id == current_user.id,
    ).first()
    if not endereco:
        raise HTTPException(status_code=404, detail="Endereço não encontrado.")

    endereco.apelido = data.apelido
    endereco.cep = data.cep
    endereco.rua = data.rua
    endereco.numero = data.numero
    endereco.complemento = data.complemento
    endereco.bairro = data.bairro
    endereco.cidade = data.cidade
    endereco.estado = data.estado

    db.commit()
    db.refresh(endereco)
    return endereco


@router.delete("/{endereco_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_endereco(
    endereco_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    endereco = db.query(Endereco).filter(
        Endereco.id == endereco_id,
        Endereco.usuario_id == current_user.id,
    ).first()
    if not endereco:
        raise HTTPException(status_code=404, detail="Endereço não encontrado.")
    db.delete(endereco)
    db.commit()
