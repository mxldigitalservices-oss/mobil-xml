import sys
from engine.core.orchestrator import Orchestrator
from engine.personas.profile_manager import ProfileManager
from engine.api_mask.obfuscator import APIObfuscator
from engine.memory.tracker import MemoryTracker

def ejecutar_prueba_general():
    print("==================================================")
    print("🚀 INICIANDO PRUEBA GENERAL DEL SISTEMA - MOBIL-XML")
    print("==================================================")

    # 1. Probar Perfiles
    perfil = ProfileManager.obtener_perfil_completo("carlos_vlogs_rd")
    print(f"👤 [1/4] Perfil cargado: {perfil['nombre_visible']} (@{perfil['username']}) - Ubicación: {perfil['ubicacion']}")

    # 2. Probar Enmascaramiento
    headers = APIObfuscator.obtener_headers_aleatorios()
    print(f"🛡️ [2/4] Enmascaramiento activo. User-Agent seleccionado: {headers['User-Agent'][:50]}...")

    # 3. Probar Memoria
    objetivo_prueba = "post_test_999"
    ya_paso = MemoryTracker.ya_interactuo(perfil["username"], objetivo_id=objetivo_prueba)
    print(f"🧠 [3/4] Estado de memoria para {objetivo_prueba}: {'Ya interactuó' if ya_paso else 'Sin registro previo (Limpio)'}")

    # 4. Probar Orquestador completo
    print(f"⚙️ [4/4] Ejecutando Orquestador central...")
    try:
        motor = Orchestrator(username="carlos_vlogs_rd", plataforma="TikTok")
        motor.ejecutar_accion_organica(
            objetivo_id=objetivo_prueba, 
            mensaje_base="¡Prueba de fuego del sistema completo, mxl! 🔥"
        )
        print("\n==================================================")
        print("✅ ¡PRUEBA EXITOSA! El sistema funciona como un reloj.")
        print("==================================================")
    except Exception as e:
        print(f"\n❌ [ERROR EN LA PRUEBA]: {e}")

if __name__ == "__main__":
    ejecutar_prueba_general()
