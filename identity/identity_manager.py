from faker import Faker

fake = Faker()

class IdentityGenerator:
    def generate_profile(self) -> dict:
        return {
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
            "email": fake.email(),
            "username": fake.user_name(),
            "user_agent": fake.user_agent(),
            "locale": "es_DO",
        }
