import threading
import time
import logging
import gc
import psutil

class MemoryManager:
    """Manage memory usage and perform cleanup"""
    def __init__(self, config):
        self.config = config
        self.cleanup_thread = None
        self.running = False
        self._stop_event = threading.Event()  # Add stop event for cleaner shutdown
    
    def start(self):
        if self.running:
            return
            
        self.running = True
        self._stop_event.clear()
        self.cleanup_thread = threading.Thread(
            target=self._periodic_cleanup,
            daemon=True,
            name="MemoryCleanup"
        )
        self.cleanup_thread.start()
        logging.info("Memory manager started")
    
    def stop(self):
        """Stop the memory manager"""
        if not self.running:
            return
            
        self.running = False
        self._stop_event.set()  # Signal thread to stop
        
        if self.cleanup_thread and self.cleanup_thread.is_alive():
            try:
                self.cleanup_thread.join(timeout=2.0)  # Reduced timeout
                if self.cleanup_thread.is_alive():
                    logging.warning("Memory cleanup thread did not stop gracefully")
            except Exception as e:
                logging.warning(f"Error stopping memory thread: {e}")
        
        logging.info("Memory manager stopped")
    
    def _periodic_cleanup(self):
        """Perform periodic memory cleanup"""
        while self.running and not self._stop_event.is_set():
            try:
                # Use wait with timeout instead of sleep for quicker shutdown
                if self._stop_event.wait(timeout=300):  # 5 minutes
                    break  # Exit if stop event is set
                
                # Force garbage collection
                collected = gc.collect()
                if collected > 0 and self.config.app.debug:
                    logging.debug(f"Garbage collector collected {collected} objects")
                
                # Check memory usage
                process = psutil.Process()
                memory_percent = process.memory_percent()
                
                if memory_percent > 80:
                    logging.warning(f"High memory usage: {memory_percent:.1f}%")
                    # Additional aggressive cleanup
                    gc.collect(generation=2)
                    
            except Exception as e:
                logging.error(f"Memory cleanup error: {str(e)}")
                # Continue running despite errors