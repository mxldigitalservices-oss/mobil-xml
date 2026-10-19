import sys
from engine.personas.profile_manager import ProfileManager
from engine.api_mask.obfuscator import APIObfuscator
from engine.memory.tracker import MemoryTracker
from engine.scheduler.human_clock import HumanClock

class Orchestrator:
    """
    Motor central que coordina la identidad, el enmascaramiento, 
    el reloj biológico y la memoria del sistema.
    """

    def __init__(self, username: str, plataforma: str):
        self.perfil = ProfileManager.obtener_perfil_completo(username)
        self.plataforma = plataforma

        if not ProfileManager.validar_perfil_humano(self.perfil):
            raise ValueError(f"El perfil {username} no cumple con los requisitos mínimos de identidad real.")

    def ejecutar_accion_organica(self, objetivo_id: str, mensaje_base: str):
        # 1. Verificar memoria previa
        if MemoryTracker.ya_interactuo(self.perfil["username"], objetivo_id):
            print(f"[MEMORIA] El perfil {self.perfil['username']} ya interactuó con {objetivo_id}. Cancelando para evitar spam.")
            return

        # 2. Verificar ventana de tiempo humana
        if not HumanClock.es_horario_operativo():
            print(f"[RELOJ] Fuera de horario operativo para {self.perfil['username']}. Reprogramando...")
            return

        # 3. Generar headers simulados
        headers = APIObfuscator.obtener_headers_aleatorios()

        # 4. Simular la pausa previa del usuario leyendo/escribiendo
        print(f"[SIMULACIÓN] {self.perfil['username']} está procesando la publicación en {self.plataforma}...")
        APIObfuscator.aplicar_pausa_humana(min_segundos=2.0, max_segundos=5.0)

        # 5. Registrar interacción en memoria
        MemoryTracker.registrar_interaccion(
            username=self.perfil["username"],
            plataforma=self.plataforma,
            objetivo_id=objetivo_id,
            contenido=mensaje_base
        )

        print(f"✅ [ÉXITO] {self.perfil['username']} interactuó en {self.plataforma} con objetivo '{objetivo_id}' usando headers legítimos.")

if __name__ == "__main__":
    motor = Orchestrator(username="carlos_vlogs_rd", plataforma="TikTok")
    motor.ejecutar_accion_organica(objetivo_id="post_9988", mensaje_base="¡Durísimo ese contenido, hermano! 🔥")
