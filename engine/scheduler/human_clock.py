import random
import time
from datetime import datetime

class HumanClock:
    """
    Controla los ritmos de ejecución simulando la jornada biológica de un usuario real.
    """

    @staticmethod
    def es_horario_operativo(hora_inicio: int = 8, hora_fin: int = 23) -> bool:
        """Verifica si la hora actual está dentro de la ventana activa del perfil."""
        hora_actual = datetime.now().hour
        return hora_inicio <= hora_actual <= hora_fin

    @staticmethod
    def espera_gaussiana_interaccion(media_segundos: float = 30.0, desviacion: float = 10.0):
        """Aplica una espera natural con distribución normal entre interacciones."""
        espera = random.gauss(media_segundos, desviacion)
        espera_real = max(5.0, espera) # Mínimo 5 segundos
        time.sleep(espera_real)
