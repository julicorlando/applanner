import bcrypt
from django.contrib.auth.hashers import BasePasswordHasher, mask_hash


class PHPBcryptPasswordHasher(BasePasswordHasher):
    """
    Valida hashes bcrypt importados do PHP password_hash/password_verify.

    Na importação, armazene:
        php_bcrypt$<hash-original-do-PHP>

    must_update=True faz o Django regravar em Argon2 após login válido.
    """
    algorithm="php_bcrypt"

    def salt(self):
        raise NotImplementedError("Hasher legado: não use para criar novas senhas.")

    def encode(self,password,salt):
        raise NotImplementedError("Hasher legado: novas senhas usam Argon2.")

    def verify(self,password,encoded):
        prefix=f"{self.algorithm}$"
        if not encoded.startswith(prefix):
            return False
        raw=encoded[len(prefix):]
        if raw.startswith("$2y$"):
            raw="$2b$"+raw[4:]
        try:
            return bcrypt.checkpw(password.encode("utf-8"),raw.encode("utf-8"))
        except (ValueError,TypeError):
            return False

    def safe_summary(self,encoded):
        raw=encoded.split("$",1)[1] if "$" in encoded else ""
        return {"algorithm":self.algorithm,"hash":mask_hash(raw)}

    def must_update(self,encoded):
        return True

    def harden_runtime(self,password,encoded):
        return
