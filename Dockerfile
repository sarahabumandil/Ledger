FROM python:3.11-slim

# ============================================
# Install system dependencies required by PyMuPDF (fitz)
# ملاحظة: استبدلنا libgl1-mesa-glx بـ libgl1
# ============================================
RUN apt-get update && apt-get install -y \
    libgl1 \
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
# Expose the port Render expects
# ============================================
ENV PORT=8000
EXPOSE 8000

# ============================================
# Run the FastAPI app with Uvicorn
# ============================================
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
