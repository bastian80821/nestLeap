"""
Authentication middleware for admin endpoints.
"""
from fastapi import Header, HTTPException, status
from typing import Optional
from .config import settings
from loguru import logger


async def verify_admin_key(x_admin_api_key: Optional[str] = Header(None)):
    """
    Verify admin API key for protected endpoints.
    
    Args:
        x_admin_api_key: API key from request header
        
    Raises:
        HTTPException: If API key is missing or invalid
        
    Returns:
        bool: True if authenticated
    """
    if not x_admin_api_key:
        logger.warning("Admin endpoint accessed without API key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin API key required. Include 'X-Admin-API-Key' header."
        )
    
    if x_admin_api_key != settings.admin_api_key:
        logger.warning(f"Admin endpoint accessed with invalid API key: {x_admin_api_key[:10]}...")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin API key"
        )
    
    logger.info("Admin authenticated successfully")
    return True

