"""
Centralized logging configuration for JRVS.
"""
import logging
import logging.handlers
import os
from pathlib import Path
from datetime import datetime
import json


class JSONFormatter(logging.Formatter):
    """Custom formatter to output logs as JSON for easy parsing."""
    
    def format(self, record):
        log_obj = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add exception info if present
        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)
            
        # Add extra fields if present
        for key, value in record.__dict__.items():
            if key not in ('name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                          'filename', 'module', 'lineno', 'funcName', 'created',
                          'msecs', 'relativeCreated', 'thread', 'threadName',
                          'processName', 'process', 'getMessage', 'exc_info',
                          'exc_text', 'stack_info'):
                log_obj[key] = value
                
        return json.dumps(log_obj)


def setup_logger(name: str = 'jrvs', level: str = 'INFO') -> logging.Logger:
    """
    Set up centralized logger for JRVS.
    
    Args:
        name: Logger name
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    
    Returns:
        Configured logger instance
    """
    # Create logs directory
    log_dir = Path.home() / 'JRVS' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger
    
    # Console handler (human readable)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_format)
    
    # File handler (JSON format for easy parsing)
    log_file = log_dir / f'jrvs_{datetime.now().strftime("%Y%m%d")}.jsonl'
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=5  # 10MB max, 5 backups
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JSONFormatter())
    
    # Add handlers
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger


def log_command(command: str, args: dict = None, **kwargs):
    """Log command execution with context."""
    logger = logging.getLogger('jrvs.command')
    logger.info('Command executed', extra={
        'command': command,
        'args': args or {},
        'context': kwargs
    })


def log_api_call(service: str, method: str, url: str = None, params: dict = None, 
                response_status: int = None, response_size: int = None, 
                duration: float = None, **kwargs):
    """Log API calls with timing and response info."""
    logger = logging.getLogger('jrvs.api')
    logger.info('API call made', extra={
        'service': service,
        'method': method,
        'url': url,
        'params': params,
        'response_status': response_status,
        'response_size': response_size,
        'duration_seconds': duration,
        'context': kwargs
    })


def log_model_interaction(model: str, prompt: str = None, response: str = None,
                         tokens_used: int = None, duration: float = None, **kwargs):
    """Log LLM model interactions."""
    logger = logging.getLogger('jrvs.model')
    logger.info('Model interaction', extra={
        'model': model,
        'prompt_length': len(prompt) if prompt else 0,
        'response_length': len(response) if response else 0,
        'tokens_used': tokens_used,
        'duration_seconds': duration,
        'context': kwargs
    })


def log_db_operation(operation: str, table: str, affected_rows: int = None,
                    duration: float = None, **kwargs):
    """Log database operations."""
    logger = logging.getLogger('jrvs.db')
    logger.info('Database operation', extra={
        'operation': operation,
        'table': table,
        'affected_rows': affected_rows,
        'duration_seconds': duration,
        'context': kwargs
    })


def log_error(error: Exception, context: dict = None, **kwargs):
    """Log errors with full context."""
    logger = logging.getLogger('jrvs.error')
    logger.error('Error occurred', extra={
        'error_type': type(error).__name__,
        'error_message': str(error),
        'context': context or {},
        'additional': kwargs
    }, exc_info=True)


def log_performance(operation: str, duration: float, **kwargs):
    """Log performance metrics."""
    logger = logging.getLogger('jrvs.performance')
    logger.info('Performance metric', extra={
        'operation': operation,
        'duration_seconds': duration,
        'metrics': kwargs
    })