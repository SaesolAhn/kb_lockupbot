"""Custom exceptions for KB Lockup"""


class KBLockupError(Exception):
    """Base exception for KB Lockup"""
    pass


class DartAPIError(KBLockupError):
    """DART API related errors"""

    def __init__(self, message: str, status_code: int = None, response: str = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class RateLimitError(DartAPIError):
    """API rate limit exceeded"""

    def __init__(self, message: str = "DART API rate limit exceeded"):
        super().__init__(message, status_code=429)


class ExtractionError(KBLockupError):
    """Table extraction failures"""

    def __init__(self, message: str, document_id: str = None, section: str = None):
        super().__init__(message)
        self.document_id = document_id
        self.section = section


class ValidationError(KBLockupError):
    """Data validation failures"""

    def __init__(self, message: str, field: str = None, value: str = None):
        super().__init__(message)
        self.field = field
        self.value = value


class DocumentNotFoundError(DartAPIError):
    """Requested document not found"""

    def __init__(self, rcept_no: str):
        super().__init__(f"Document not found: {rcept_no}", status_code=404)
        self.rcept_no = rcept_no


class ParsingError(KBLockupError):
    """Document parsing failures"""

    def __init__(self, message: str, document_type: str = None):
        super().__init__(message)
        self.document_type = document_type


class DatabaseError(KBLockupError):
    """Database operation failures"""
    pass


class ConfigurationError(KBLockupError):
    """Configuration/settings errors"""
    pass
