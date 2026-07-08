ORDER_STATUS_AGUARDANDO = "Aguardando pagamento"
ORDER_STATUS_PAGO = "Pago"
ORDER_STATUS_PREPARANDO = "Preparando"
ORDER_STATUS_ENVIADO = "Enviado"
ORDER_STATUS_ENTREGUE = "Entregue"
ORDER_STATUS_CANCELADO = "Cancelado"
ORDER_STATUS_RECUSADO = "Pagamento recusado"
ORDER_STATUS_REEMBOLSADO = "Reembolsado"
ORDER_STATUS_EXPIRADO = "Pagamento expirado"
ORDER_STATUS_ESTORNADO = "Estornado"

ORDER_STATUSES = {
    ORDER_STATUS_AGUARDANDO,
    ORDER_STATUS_PAGO,
    ORDER_STATUS_PREPARANDO,
    ORDER_STATUS_ENVIADO,
    ORDER_STATUS_ENTREGUE,
    ORDER_STATUS_CANCELADO,
    ORDER_STATUS_RECUSADO,
    ORDER_STATUS_REEMBOLSADO,
    ORDER_STATUS_EXPIRADO,
    ORDER_STATUS_ESTORNADO,
}

ORDER_STATUS_EMAIL_EVENTS = {
    ORDER_STATUS_PAGO: "payment_approved",
    ORDER_STATUS_PREPARANDO: "order_preparing",
    ORDER_STATUS_ENVIADO: "order_shipped",
    ORDER_STATUS_ENTREGUE: "order_delivered",
    ORDER_STATUS_CANCELADO: "order_cancelled",
    ORDER_STATUS_RECUSADO: "payment_refused",
    ORDER_STATUS_REEMBOLSADO: "refund_completed",
    ORDER_STATUS_EXPIRADO: "payment_expired",
}

MP_TO_ORDER_STATUS = {
    "approved": ORDER_STATUS_PAGO,
    "pending": ORDER_STATUS_AGUARDANDO,
    "in_process": ORDER_STATUS_AGUARDANDO,
    "rejected": ORDER_STATUS_RECUSADO,
    "cancelled": ORDER_STATUS_CANCELADO,
    "refunded": ORDER_STATUS_REEMBOLSADO,
    "charged_back": ORDER_STATUS_ESTORNADO,
}

MP_TO_PAYMENT_STATUS = {
    "approved": "aprovado",
    "pending": "pendente",
    "in_process": "em_analise",
    "rejected": "recusado",
    "cancelled": "cancelado",
    "refunded": "reembolsado",
    "charged_back": "estornado",
}

PAYMENT_EMAIL_EVENTS = {
    "approved": "payment_approved",
    "pending": "payment_pending",
    "in_process": "payment_pending",
    "rejected": "payment_refused",
    "cancelled": "payment_expired",
    "refunded": "refund_completed",
    "charged_back": "payment_refused",
}
