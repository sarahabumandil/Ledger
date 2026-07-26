FROM python:3.11-slim

# ============================================
# Install system dependencies required by PyMuPDF (fitz)
# ============================================
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    wget \
    && rm -rf /var/lib/apt/lists/*

# ============================================
# Set working directory
# ============================================
WORKDIR /app

# ============================================
# Copy and install Python dependencies
# ============================================
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ============================================
# Copy the rest of the application code
# ============================================
COPY . .

# ============================================
# Expose the port Hugging Face Spaces expects
# ============================================
ENV PORT=7860
EXPOSE 7860

# ============================================
# Run the FastAPI app with Uvicorn
# ============================================
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
