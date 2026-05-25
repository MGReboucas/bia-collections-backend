from typing import List, Dict


def formatar_preco(valor: float) -> str:
    """Formata valor para o padrão brasileiro: R$ 99,90"""
    formatted = f"{valor:,.2f}"
    # Python uses comma as thousands separator and dot as decimal
    # We need to swap: dot -> comma, comma -> dot
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def calcular_frete(cep_destino: str, peso_total: float = 0.5) -> List[Dict]:
    """
    Simula cálculo de frete por região (prefixo do CEP).
    Estrutura pronta para integrar Correios/Melhor Envio futuramente.
    """
    cep_limpo = "".join(c for c in cep_destino if c.isdigit())
    try:
        prefixo = int(cep_limpo[:2]) if cep_limpo else 0
    except ValueError:
        prefixo = 0

    # Regiões aproximadas por prefixo do CEP
    if 1 <= prefixo <= 19:       # São Paulo (capital e região)
        pac_valor, sedex_valor = 12.90, 24.90
    elif 20 <= prefixo <= 28:    # Rio de Janeiro
        pac_valor, sedex_valor = 15.90, 29.90
    elif 29 <= prefixo <= 29:    # Espírito Santo
        pac_valor, sedex_valor = 16.90, 31.90
    elif 30 <= prefixo <= 39:    # Minas Gerais
        pac_valor, sedex_valor = 14.90, 27.90
    elif 40 <= prefixo <= 48:    # Bahia
        pac_valor, sedex_valor = 18.90, 35.90
    elif 49 <= prefixo <= 49:    # Sergipe
        pac_valor, sedex_valor = 19.90, 36.90
    elif 50 <= prefixo <= 56:    # Pernambuco
        pac_valor, sedex_valor = 20.90, 38.90
    elif 57 <= prefixo <= 57:    # Alagoas
        pac_valor, sedex_valor = 21.90, 39.90
    elif 58 <= prefixo <= 58:    # Paraíba
        pac_valor, sedex_valor = 21.90, 39.90
    elif 59 <= prefixo <= 59:    # Rio Grande do Norte
        pac_valor, sedex_valor = 22.90, 40.90
    elif 60 <= prefixo <= 63:    # Ceará
        pac_valor, sedex_valor = 22.90, 41.90
    elif 64 <= prefixo <= 64:    # Piauí
        pac_valor, sedex_valor = 23.90, 42.90
    elif 65 <= prefixo <= 65:    # Maranhão
        pac_valor, sedex_valor = 24.90, 44.90
    elif 66 <= prefixo <= 68:    # Pará
        pac_valor, sedex_valor = 26.90, 48.90
    elif 69 <= prefixo <= 69:    # Amazonas / Roraima
        pac_valor, sedex_valor = 28.90, 52.90
    elif 70 <= prefixo <= 73:    # Brasília / DF / Goiás
        pac_valor, sedex_valor = 16.90, 30.90
    elif 74 <= prefixo <= 76:    # Goiás
        pac_valor, sedex_valor = 17.90, 32.90
    elif 77 <= prefixo <= 77:    # Tocantins
        pac_valor, sedex_valor = 22.90, 41.90
    elif 78 <= prefixo <= 78:    # Mato Grosso
        pac_valor, sedex_valor = 20.90, 38.90
    elif 79 <= prefixo <= 79:    # Mato Grosso do Sul
        pac_valor, sedex_valor = 18.90, 34.90
    elif 80 <= prefixo <= 87:    # Paraná
        pac_valor, sedex_valor = 14.90, 27.90
    elif 88 <= prefixo <= 89:    # Santa Catarina
        pac_valor, sedex_valor = 15.90, 28.90
    elif 90 <= prefixo <= 99:    # Rio Grande do Sul
        pac_valor, sedex_valor = 16.90, 31.90
    else:
        pac_valor, sedex_valor = 17.90, 33.90

    return [
        {
            "nome": "PAC",
            "prazo": "7 a 10 dias úteis",
            "valor": pac_valor,
            "valor_formatado": formatar_preco(pac_valor),
        },
        {
            "nome": "SEDEX",
            "prazo": "2 a 4 dias úteis",
            "valor": sedex_valor,
            "valor_formatado": formatar_preco(sedex_valor),
        },
    ]
