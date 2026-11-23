"""API de demostración para observabilidad de un servicio SOA.

Expone sondajes de salud, métricas en formato Prometheus y una operación
simulada de negocio. El estado y las métricas se mantienen en memoria; por
tanto, se reinician al reiniciar el proceso y no están preparados para producción.

Para ejecutar el servicio desde la carpeta del proyecto:
    uvicorn observability_main:app --reload
"""

import time
import random
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Response, HTTPException, status
from fastapi.responses import PlainTextResponse, JSONResponse
from pydantic import BaseModel, Field

# ==============================================================================
# ⚙️ CONFIGURACIÓN GENERAL Y ESTADO DE LA APLICACIÓN
# ==============================================================================
app = FastAPI(
    title="API de Observabilidad SOA: Métricas RED/USE y Health Checks",
    version="1.0.0",
    description="Demostración de telemetría con Prometheus y sondajes Liveness/Readiness"
)

# Estado simulado de dependencias de infraestructura. Se usa principalmente
# para demostrar el comportamiento de readiness y el endpoint administrativo.
DB_CONEXION_ACTIVA: bool = True
RABBITMQ_ACTIVO: bool = True

# ==============================================================================
# 📊 MOTOR SIMPLE DE MÉTRICAS COMPATIBLE CON PROMETHEUS
# ==============================================================================
class PrometheusMetricsEngine:
    """Almacena contadores, gauges y datos agregados de latencia en memoria."""

    def __init__(self):
        """Inicializa las estructuras y valores iniciales de las métricas."""
        # Counter: http_requests_total{method, endpoint, status_code} -> int
        self.counters: Dict[str, int] = {}
        # Gauge: system_metric{name} -> float
        self.gauges: Dict[str, float] = {
            "system_memory_usage_percent": 42.5,
            "active_db_connections": 8.0
        }
        # Histogram Buckets para latencia (en segundos)
        self.buckets = [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
        # Histogram data
        self.histogram_sum: float = 0.0
        self.histogram_total_count: int = 0

    def increment_counter(self, method: str, endpoint: str, status_code: int):
        """Incrementa el contador de solicitudes identificado por sus etiquetas."""
        key = f'http_requests_total{{method="{method}",endpoint="{endpoint}",status="{status_code}"}}'
        self.counters[key] = self.counters.get(key, 0) + 1

    def set_gauge(self, name: str, value: float):
        """Actualiza un gauge redondeando su valor para facilitar su lectura."""
        self.gauges[name] = round(value, 2)

    def observe_duration(self, duration: float):
        """Agrega una observación al total y al número de solicitudes medidas."""
        self.histogram_sum += duration
        self.histogram_total_count += 1

    def generate_prometheus_text(self) -> str:
        """Serializa las métricas actuales en texto legible por Prometheus."""
        lines = []
        
        # 1. Métrica Counter (RED: Rate & Errors)
        lines.append("# HELP http_requests_total Total de solicitudes HTTP procesadas por el servicio.")
        lines.append("# TYPE http_requests_total counter")
        for key, val in self.counters.items():
            lines.append(f"{key} {val}")
            
        # 2. Métrica Gauge (USE: Utilization & Saturation)
        lines.append("\n# HELP system_memory_usage_percent Porcentaje de memoria RAM en uso.")
        lines.append("# TYPE system_memory_usage_percent gauge")
        lines.append(f"system_memory_usage_percent {self.gauges.get('system_memory_usage_percent', 0.0)}")
        
        lines.append("\n# HELP active_db_connections Conexiones activas en el pool de base de datos.")
        lines.append("# TYPE active_db_connections gauge")
        lines.append(f"active_db_connections {self.gauges.get('active_db_connections', 0.0)}")

        # 3. Métrica Histogram (RED: Duration)
        lines.append("\n# HELP http_request_duration_seconds Latencia de procesamiento HTTP en segundos.")
        lines.append("# TYPE http_request_duration_seconds summary")
        lines.append(f"http_request_duration_seconds_sum {round(self.histogram_sum, 4)}")
        lines.append(f"http_request_duration_seconds_count {self.histogram_total_count}")
        
        return "\n".join(lines) + "\n"

# Instancia global del motor de métricas
metrics_engine = PrometheusMetricsEngine()

# ==============================================================================
# 🛡️ MIDDLEWARE DE TELEMETRÍA RED (RATE, ERRORS, DURATION)
# ==============================================================================
@app.middleware("http")
async def middleware_telemetria_red(request: Request, call_next):
    """Mide la duración y registra una métrica para cada respuesta HTTP.

    Si el manejo de la solicitud genera una excepción, se registra como un
    error 500 y la excepción se vuelve a lanzar para conservar el manejo
    normal de errores del framework.
    """
    # Medición de latencia de inicio (Duration)
    start_time = time.perf_counter()
    
    try:
        # ``call_next`` es asíncrono; esperarlo garantiza recibir la respuesta HTTP.
        response: Response = await call_next(request)
        duration = time.perf_counter() - start_time
        
        # Registrar métricas RED en tiempo real
        endpoint = request.url.path
        method = request.method
        status_code = response.status_code
        
        metrics_engine.increment_counter(method, endpoint, status_code)
        metrics_engine.observe_duration(duration)
        
        # Inyectar cabecera telemétrica en la respuesta
        response.headers["X-Response-Time-Seconds"] = f"{duration:.4f}"
        return response
    except Exception:
        duration = time.perf_counter() - start_time
        metrics_engine.increment_counter(request.method, request.url.path, 500)
        metrics_engine.observe_duration(duration)
        raise

# ==============================================================================
# 🔄 TAREA DE FONDO: SIMULADOR DE INFRAESTRUCTURA USE
# ==============================================================================
async def simulador_recursos_use():
    """Actualiza periódicamente gauges con valores aleatorios de demostración."""
    while True:
        await asyncio.sleep(5)
        memory = random.uniform(35.0, 88.0)
        connections = random.randint(3, 25)
        metrics_engine.set_gauge("system_memory_usage_percent", memory)
        metrics_engine.set_gauge("active_db_connections", float(connections))

@app.on_event("startup")
async def startup_event():
    """Inicia el simulador de recursos como tarea de fondo de la aplicación."""
    asyncio.create_task(simulador_recursos_use())

# ==============================================================================
# 🩺 ENDPOINTS DE SONDAJES DE SALUD (HEALTH CHECKS)
# ==============================================================================
@app.get("/health/liveness", tags=["Health Checks"])
def liveness_probe():
    """Indica que el proceso de la API está disponible para recibir solicitudes."""
    return {
        "status": "UP",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "componente": "FastAPI Core Event Loop"
    }

@app.get("/health/readiness", tags=["Health Checks"])
def readiness_probe():
    """Comprueba disponibilidad simulada de la base de datos y RabbitMQ.

    Devuelve HTTP 503 si al menos una dependencia está caída y HTTP 200
    únicamente cuando ambas dependencias están activas.
    """
    detalles = {
        "database": "UP" if DB_CONEXION_ACTIVA else "DOWN",
        "rabbitmq": "UP" if RABBITMQ_ACTIVO else "DOWN"
    }
    
    if not (DB_CONEXION_ACTIVA and RABBITMQ_ACTIVO):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "DOWN",
                "motivo": "Una o más dependencias críticas no están disponibles",
                "detalles": detalles,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )
        
    return {
        "status": "UP",
        "detalles": detalles,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# ==============================================================================
# 📊 ENDPOINT NATIVO DE MÉTRICAS DE PROMETHEUS
# ==============================================================================
@app.get("/metrics", response_class=PlainTextResponse, tags=["Observabilidad"])
def expose_prometheus_metrics():
    """Publica los contadores, gauges y agregados de latencia actuales."""
    return metrics_engine.generate_prometheus_text()

# ==============================================================================
# 📦 MODELOS DTO Y ENDPOINTS DE NEGOCIO SIMULADOS
# ==============================================================================
class SolicitudServicioDTO(BaseModel):
    """Datos validados que requiere la operación de negocio simulada."""

    cliente_id: str = Field(..., examples=["CLI-9941"])
    servicio_tipo: str = Field(..., examples=["CONSULTA_SALDO"])
    prioridad: int = Field(1, ge=1, le=5)

@app.post("/v1/servicios/procesar", tags=["Servicios de Negocio"])
def procesar_servicio(payload: SolicitudServicioDTO):
    """Procesa una solicitud ficticia y responde con su folio y latencia.

    La pausa y el error aleatorios representan latencia y fallos de negocio;
    esta operación no consulta sistemas externos ni realiza transacciones.
    """
    # Simular latencia de procesamiento aleatoria
    latencia_simulada = random.uniform(0.05, 0.45)
    time.sleep(latencia_simulada)
    
    # Simular fallo aleatorio (5% de probabilidad)
    if random.random() < 0.05:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error simulado en la capa de procesamiento de negocio"
        )
        
    return {
        "folio": f"FOL-{random.randint(10000, 99999)}",
        "clienteId": payload.cliente_id,
        "tipo": payload.servicio_tipo,
        "estado": "COMPLETADO",
        "latencia_procesamiento": f"{latencia_simulada:.4f}s"
    }

# Endpoint administrativo para simular caídas de dependencias
@app.post("/admin/simular-falla-db", tags=["Administración"])
def simular_falla_db(activa: bool):
    """Cambia el estado simulado de la base de datos para probar readiness.

    El parámetro ``activa`` se recibe como query string; al establecerlo en
    ``false``, ``/health/readiness`` responderá con HTTP 503.
    """
    global DB_CONEXION_ACTIVA
    DB_CONEXION_ACTIVA = activa
    return {"mensaje": f"Conexión a Base de Datos establecida en: {DB_CONEXION_ACTIVA}"}