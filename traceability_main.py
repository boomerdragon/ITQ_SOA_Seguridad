"""API educativa de trazabilidad distribuida y contexto W3C Trace Context.

El middleware extrae ``traceparent`` de cada solicitud y crea un span HTTP raíz.
La operación de pedidos agrega spans hijos para inventario y pagos; los
endpoints de telemetría permiten consultar los spans guardados en memoria.

El ``JaegerCollectorService`` es una simulación local: no exporta OTLP ni se
conecta a Jaeger. Los retardos y servicios externos también son simulados.
Para iniciar desde la carpeta del proyecto:
    uvicorn traceability_main:app --reload
"""

import time
import uuid
import secrets
import re
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
from fastapi import FastAPI, Request, Response, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ==============================================================================
# ⚙️ CONFIGURACIÓN INICIAL Y APLICACIÓN FASTAPI
# ==============================================================================
app = FastAPI(
    title="Servicio de Procesamiento de Pedidos con OpenTelemetry y W3C Trace Context",
    description="Demostración completa de Trazabilidad Distribuida, Spans jerárquicos y exportación OTLP/Jaeger.",
    version="1.0.0"
)

# ==============================================================================
# 📦 MODELOS DTO (DATOS DE ENTRADA Y SALIDA)
# ==============================================================================
class ElementoPedidoDTO(BaseModel):
    """Producto y cantidad que el cliente desea incluir en un pedido."""

    producto_id: str = Field(..., examples=["PROD-8821"])
    cantidad: int = Field(..., gt=0, examples=[2])
    precio_unitario: float = Field(..., gt=0.0, examples=[450.50])

class SolicitudPedidoDTO(BaseModel):
    """Datos validados para procesar un pedido con uno o más elementos."""

    cliente_id: str = Field(..., examples=["CLI-99412"])
    metodo_pago: str = Field(..., examples=["TARJETA_CREDITO"])
    elementos: List[ElementoPedidoDTO]

# ==============================================================================
# 🔍 MOTOR DE TRAZABILIDAD Y ESTÁNDAR W3C TRACE CONTEXT
# ==============================================================================
class W3CTraceContextEngine:
    """Genera y procesa los identificadores del encabezado W3C ``traceparent``.

    El formato de versión 00 es ``00-{trace-id}-{parent-id}-{trace-flags}``,
    con identificadores de 32 y 16 caracteres hexadecimales respectivamente.
    """

    # Expresión para el formato traceparent versión 00 usado por esta demo.
    W3C_REGEX = re.compile(r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")

    @staticmethod
    def generate_trace_id() -> str:
        """Crea un Trace ID aleatorio de 128 bits representado por 32 hex."""
        return secrets.token_hex(16)

    @staticmethod
    def generate_span_id() -> str:
        """Crea un Span ID aleatorio de 64 bits representado por 16 hex."""
        return secrets.token_hex(8)

    @classmethod
    def parse_traceparent(cls, traceparent_header: Optional[str]) -> Dict[str, Optional[str]]:
        """Extrae versión, Trace ID, span padre y flags del encabezado.

        Ante un valor ausente o inválido devuelve campos nulos para que el
        middleware inicie una traza nueva.
        """
        if not traceparent_header:
            return {"version": None, "trace_id": None, "parent_span_id": None, "flags": None}

        match = cls.W3C_REGEX.match(traceparent_header.strip())
        if not match:
            return {"version": None, "trace_id": None, "parent_span_id": None, "flags": None}

        version, trace_id, parent_span_id, flags = match.groups()
        return {
            "version": version,
            "trace_id": trace_id,
            "parent_span_id": parent_span_id,
            "flags": flags
        }

    @classmethod
    def build_traceparent(cls, trace_id: str, span_id: str, sampled: bool = True) -> str:
        """Serializa el contexto de un span como ``traceparent`` versión 00."""
        flags = "01" if sampled else "00"
        return f"00-{trace_id}-{span_id}-{flags}"

# ==============================================================================
# ⏱️ MODELO DE SPAN Y ALMACENAMIENTO DE TRAZAS EN MEMORIA
# ==============================================================================
class SpanContext:
    """Unidad de trabajo dentro de una traza, con relación padre-hijo y eventos.

    ``perf_counter`` mide la duración y el timestamp UTC registra el inicio
    legible por humanos. Los atributos aportan contexto al span.
    """

    def __init__(self, name: str, trace_id: str, parent_span_id: Optional[str] = None):
        """Inicializa el contexto y comienza la medición del span."""
        self.name: str = name
        self.trace_id: str = trace_id
        self.span_id: str = W3CTraceContextEngine.generate_span_id()
        self.parent_span_id: Optional[str] = parent_span_id
        self.start_time: float = time.perf_counter()
        self.start_timestamp_iso: str = datetime.now(timezone.utc).isoformat()
        self.end_time: Optional[float] = None
        self.duration_ms: Optional[float] = None
        self.status: str = "OK"
        self.attributes: Dict[str, Any] = {}
        self.events: List[Dict[str, Any]] = []

    def set_attribute(self, key: str, value: Any) -> None:
        """Asocia metadatos clave-valor al span, por ejemplo ``http.method``."""
        self.attributes[key] = value

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        """Registra un evento puntual con hora UTC y atributos opcionales."""
        self.events.append({
            "name": name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attributes": attributes or {}
        })

    def finish(self, status_code: str = "OK") -> None:
        """Detiene el cronómetro y guarda duración en milisegundos y estado."""
        self.end_time = time.perf_counter()
        self.duration_ms = round((self.end_time - self.start_time) * 1000, 2)
        self.status = status_code

    def to_dict(self) -> Dict[str, Any]:
        """Convierte el span a la estructura JSON utilizada por la API."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "start_time": self.start_timestamp_iso,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events
        }

class JaegerCollectorService:
    """Recolector didáctico en memoria para recuperar spans por Trace ID.

    El nombre alude al destino habitual, pero esta implementación no integra
    Jaeger ni implementa el protocolo de exportación OTLP.
    """

    def __init__(self):
        """Prepara el almacenamiento que vive mientras el proceso esté activo."""
        self._spans_storage: List[SpanContext] = []

    def record_span(self, span: SpanContext) -> None:
        """Añade un span finalizado al almacenamiento local."""
        self._spans_storage.append(span)

    def get_trace_by_id(self, trace_id: str) -> List[Dict[str, Any]]:
        """Devuelve los spans de una traza específica como diccionarios."""
        matching_spans = [s for s in self._spans_storage if s.trace_id == trace_id]
        return [s.to_dict() for s in matching_spans]

    def get_all_spans(self) -> List[Dict[str, Any]]:
        """Devuelve una instantánea serializable de todos los spans guardados."""
        return [s.to_dict() for s in self._spans_storage]

jaeger_collector = JaegerCollectorService()

# ==============================================================================
# 🛡️ MIDDLEWARE DE INSTRUMENTALIZACIÓN OPENTELEMETRY
# ==============================================================================
@app.middleware("http")
async def middleware_opentelemetry_tracing(request: Request, call_next):
    """Continúa el contexto entrante y mide cada solicitud HTTP.

    Si no hay un ``traceparent`` reconocido, crea un Trace ID nuevo. El span
    raíz se adjunta a ``request.state`` para que el endpoint cree spans hijos.
    """
    raw_traceparent = request.headers.get("traceparent")
    parsed_context = W3CTraceContextEngine.parse_traceparent(raw_traceparent)

    # Un servicio puede continuar una traza iniciada por otro componente.
    trace_id = parsed_context["trace_id"] or W3CTraceContextEngine.generate_trace_id()
    parent_span_id = parsed_context["parent_span_id"]

    span_name = f"HTTP {request.method} {request.url.path}"
    root_span = SpanContext(name=span_name, trace_id=trace_id, parent_span_id=parent_span_id)
    root_span.set_attribute("http.method", request.method)
    root_span.set_attribute("http.url", str(request.url))
    root_span.set_attribute("http.target", request.url.path)
    root_span.set_attribute("http.user_agent", request.headers.get("user-agent", "Desconocido"))

    request.state.trace_id = trace_id
    request.state.root_span = root_span

    try:
        # Espera la respuesta para registrar estado, duración y cabeceras.
        response: Response = await call_next(request)

        root_span.set_attribute("http.status_code", response.status_code)
        status_flag = "OK" if response.status_code < 400 else "ERROR"
        root_span.finish(status_code=status_flag)

        # El span raíz de este servicio será el padre del siguiente salto.
        outgoing_traceparent = W3CTraceContextEngine.build_traceparent(trace_id, root_span.span_id)
        response.headers["traceparent"] = outgoing_traceparent
        response.headers["X-Trace-ID"] = trace_id

        jaeger_collector.record_span(root_span)
        return response

    except Exception as exc:
        # La excepción se registra y se relanza para conservar el manejo de FastAPI.
        root_span.set_attribute("http.status_code", 500)
        root_span.add_event("exception", {"exception.message": str(exc), "exception.type": type(exc).__name__})
        root_span.finish(status_code="ERROR")
        jaeger_collector.record_span(root_span)
        raise exc

# ==============================================================================
# 🛠️ CAPA DE LÓGICA DE NEGOCIO CON SPANS HIJOS
# ==============================================================================
def simular_operacion_inventario(trace_id: str, parent_span_id: str, elementos: List[ElementoPedidoDTO]) -> bool:
    """Crea un span hijo para consultar inventario y simula su latencia."""
    span = SpanContext(name="DB SELECT inventario_stock", trace_id=trace_id, parent_span_id=parent_span_id)
    span.set_attribute("db.system", "postgresql")
    span.set_attribute("db.operation", "SELECT")
    span.set_attribute("items.count", len(elementos))

    # La pausa ilustra duración; esta función no consulta una base real.
    time.sleep(0.05)
    span.add_event("stock_verificado", {"status": "disponible"})
    span.finish(status_code="OK")
    jaeger_collector.record_span(span)
    return True

def simular_servicio_pagos_externo(trace_id: str, parent_span_id: str, monto_total: float, metodo: str) -> str:
    """Representa un salto HTTP a pagos y genera un ID de transacción simulado."""
    span = SpanContext(name="HTTP POST /v1/gateway/pago", trace_id=trace_id, parent_span_id=parent_span_id)
    span.set_attribute("peer.service", "PasarelaPagosExterno")
    span.set_attribute("payment.amount", monto_total)
    span.set_attribute("payment.method", metodo)

    # Este encabezado ilustra cómo se propagaría el contexto al servicio externo.
    outgoing_header = W3CTraceContextEngine.build_traceparent(trace_id, span.span_id)
    span.add_event("http_request_sent", {"headers.traceparent": outgoing_header})

    time.sleep(0.12)

    transaccion_id = f"TXN-{uuid.uuid4().hex[:8].upper()}"
    span.set_attribute("payment.transaction_id", transaccion_id)
    span.add_event("payment_approved", {"transaction_id": transaccion_id})
    span.finish(status_code="OK")
    jaeger_collector.record_span(span)
    return transaccion_id

# ==============================================================================
# 🚪 ENDPOINTS DE LA APLICACIÓN
# ==============================================================================
@app.post("/v1/pedidos/procesar", tags=["Procesamiento de Pedidos"])
def procesar_pedido(payload: SolicitudPedidoDTO, request: Request):
    """Procesa un pedido simulado y agrega spans hijos al span HTTP raíz.

    No consulta sistemas externos reales; devuelve folio, pago y contexto de
    trazabilidad para que el cliente pueda continuar o consultar la traza.
    """
    trace_id = request.state.trace_id
    root_span: SpanContext = request.state.root_span

    # Atributos de negocio enriquecen el span raíz con contexto del pedido.
    monto_total = sum(item.cantidad * item.precio_unitario for item in payload.elementos)
    root_span.set_attribute("order.cliente_id", payload.cliente_id)
    root_span.set_attribute("order.monto_total", monto_total)

    inventario_ok = simular_operacion_inventario(
        trace_id=trace_id,
        parent_span_id=root_span.span_id,
        elementos=payload.elementos
    )

    if not inventario_ok:
        raise HTTPException(status_code=400, detail="Stock insuficiente para procesar el pedido.")

    transaccion_id = simular_servicio_pagos_externo(
        trace_id=trace_id,
        parent_span_id=root_span.span_id,
        monto_total=monto_total,
        metodo=payload.metodo_pago
    )

    folio_pedido = f"PED-{uuid.uuid4().hex[:6].upper()}"
    root_span.add_event("pedido_completado", {"folio": folio_pedido, "transaccion_id": transaccion_id})

    return {
        "mensaje": "Pedido procesado exitosamente",
        "folio_pedido": folio_pedido,
        "transaccion_pago_id": transaccion_id,
        "monto_total": monto_total,
        "telemetria": {
            "trace_id": trace_id,
            "w3c_traceparent": W3CTraceContextEngine.build_traceparent(trace_id, root_span.span_id)
        }
    }

@app.get("/v1/telemetry/spans", tags=["Observabilidad & Jaeger UI"])
def listar_todos_los_spans():
    """Lista todos los spans almacenados desde el inicio del proceso."""
    return {
        "total_spans": len(jaeger_collector.get_all_spans()),
        "spans": jaeger_collector.get_all_spans()
    }

@app.get("/v1/telemetry/trace/{trace_id}", tags=["Observabilidad & Jaeger UI"])
def consultar_traza_por_id(trace_id: str):
    """Busca los spans relacionados con un Trace ID o responde HTTP 404."""
    spans = jaeger_collector.get_trace_by_id(trace_id)
    if not spans:
        raise HTTPException(status_code=404, detail=f"No se encontraron trazas para el Trace ID: {trace_id}")

    return {
        "trace_id": trace_id,
        "total_spans_in_trace": len(spans),
        "spans_hierarchy": spans
    }