#!/bin/bash

# Stock Analysis Platform - Development Startup Script
echo "🚀 Starting Stock Analysis Platform..."

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

# Create .env files if they don't exist
echo "📝 Setting up environment files..."

if [ ! -f backend/.env ]; then
    echo "Creating backend/.env with your API keys..."
    cp backend/env.example backend/.env
    echo "✅ Backend environment configured with your API keys!"
else
    echo "📄 Backend .env file already exists"
fi

if [ ! -f frontend/.env.local ]; then
    echo "Creating frontend/.env.local..."
    echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > frontend/.env.local
fi

# Start services
echo "🐳 Starting Docker services..."
docker-compose up --build -d

# Wait for services to be healthy
echo "⏳ Waiting for services to start..."
sleep 10

# Check if services are running
if docker-compose ps | grep -q "Up"; then
    echo "✅ Services started successfully!"
    echo ""
    echo "🌐 Frontend: http://localhost:3000"
    echo "🔧 Backend API: http://localhost:8000"
    echo "📚 API Docs: http://localhost:8000/docs"
    echo ""
    echo "📊 Database: PostgreSQL on localhost:5432"
    echo "🔄 Redis: localhost:6379"
    echo ""
    echo "To stop: docker-compose down"
    echo "To view logs: docker-compose logs -f"
else
    echo "❌ Some services failed to start. Check logs with: docker-compose logs"
    exit 1
fi 