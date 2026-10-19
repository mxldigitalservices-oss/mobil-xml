import random

# Base de datos local simulada / conectable a MongoDB o SQL para almacenar modismos aprendidos
MODISMOS_REGIONALES = {
    "CO": [
        "esta chimba el video", "mucho talento parce", "uff no la cree", 
        "totalmente de acuerdo mano", "qué buena buena", "nada que decir, excelente"
    ],
    "DO": [
        "demasiado duro mi hermano", "activo con eso 🚀", "ta heavy eso ve", 
        "fuego puro con el proyecto", "demasiado cabr*n", "bendiciones mi gente"
    ],
    "GENERICO": [
        "buenísimo contenido", "sigue así bro", "me encantó esta parte", 
        "esto necesitaba ver hoy", "excelente aporte a la comunidad"
    ]
}

class GestorModismos:
    @staticmethod
    def obtener_modismo(pais: str = "GENERICO") -> str:
        lista = MODISMOS_REGIONALES.get(pais.upper(), MODISMOS_REGIONALES["GENERICO"])
        return random.choice(lista)

    @staticmethod
    def registrar_nuevo_modismo(pais: str, modismo: str):
        pais_key = pais.upper()
        if pais_key not in MODISMOS_REGIONALES:
            MODISMOS_REGIONALES[pais_key] = []
        if modismo not in MODISMOS_REGIONALES[pais_key]:
            MODISMOS_REGIONALES[pais_key].append(modismo)
