const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

// Load environment variables
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 3000;

// Security middleware
app.use(helmet());
app.use(cors({
    origin: process.env.ALLOWED_ORIGINS ? process.env.ALLOWED_ORIGINS.split(',') : ['http://localhost:3000'],
    credentials: true
}));

// Rate limiting
const limiter = rateLimit({
    windowMs: 15 * 60 * 1000, // 15 minutes
    max: 100, // limit each IP to 100 requests per windowMs
    message: 'Too many requests from this IP, please try again later.'
});
app.use(limiter);

app.use(express.json({ limit: '10mb' }));

// In-memory storage for sessions (in production, use Redis or database)
const userSessions = new Map();

// Health check endpoint
app.get('/health', (req, res) => {
    res.json({ status: 'ok', timestamp: new Date().toISOString() });
});




// Search function using Python script
function searchKnowledgeBase(query, topK = 5) {
    const projectRoot = path.join(__dirname, '..'); // ai-assistant root
    
    return new Promise((resolve, reject) => {
        const pythonScript = path.join(__dirname, '..', 'data-extraction', 'search.py');
        const python = process.env.PYTHON_PATH || 'python';
        
        const proc = spawn(python, [pythonScript, query, topK.toString()], {
            stdio: ['pipe', 'pipe', 'pipe']
        });
        
        let output = '';
        let errorOutput = '';
        
        proc.stdout.on('data', (data) => {
            output += data.toString();
        });
        
        proc.stderr.on('data', (data) => {
            errorOutput += data.toString();
        });
        
        proc.on('close', (code) => {
            if (code === 0) {
                try {
                    const results = JSON.parse(output);
                    resolve(results);
                } catch (error) {
                    reject(new Error(`Failed to parse search results: ${error.message}`));
                }
            } else {
                reject(new Error(`Search failed: ${errorOutput}`));
            }
        });
    });
}

// Chat endpoint
app.post('/api/chat', async (req, res) => {
    try {
        
        const { message, sessionId } = req.body;
        
        if (!message || !sessionId) {
            return res.status(400).json({
                error: 'Message and sessionId are required'
            });
        }
        
        // Get or create user session
        let session = userSessions.get(sessionId) || {
            id: sessionId,
            createdAt: new Date().toISOString(),
            context: {},
            messages: []
        };
        
        // Add user message to session
        session.messages.push({
            role: 'user',
            content: message,
            timestamp: new Date().toISOString()
        });
        
        let response = '';
        let searchResults = [];
        
        // Check if this is an order tracking request
        if (isOrderTrackingQuery(message)) {
            response = await handleOrderTracking(message, session);
        } else {
            // Search knowledge base for relevant information
            searchResults = await searchKnowledgeBase(message, 5);
            response = await generateResponse(message, searchResults, session);
        }
        
        let rawResults;
        try {
        rawResults = await searchKnowledgeBase(message, 5);
        } catch (e) {
        console.error('search failed:', e);
        // Optional: early graceful reply
        return res.status(200).json({
            response: "I'm having trouble searching the knowledge base right now. Please try again shortly.",
            sessionId
        });
        }

        const normResults = Array.isArray(rawResults) ? rawResults : [];
        if (!Array.isArray(rawResults)) {
        console.warn('searchResults not array:', rawResults);
        }

        // Add assistant response to session
        session.messages.push({
            role: 'assistant',
            content: response,
            timestamp: new Date().toISOString(),
            searchResults: normResults.map(r => ({
            title: r.title,
            url: r.url,
            score: r.score
        }))
        });
        
        // Update session
        userSessions.set(sessionId, session);
        
        return res.json({
            response: response,
            sessionId: sessionId,
            sources: normResults.slice(0, 3).map(r => ({
            title: r.title,
            url: r.url,
            score: r.score
        }))
        });
        
    } catch (error) {
        console.error('Chat error:', error);
        res.status(500).json({
            error: 'Internal server error',
            message: 'Failed to process your message. Please try again.'
        });
    }
});

// Order tracking endpoint
app.post('/api/track-order', (req, res) => {
    try {
        const { orderId, sessionId, customerInfo } = req.body;
        
        if (!orderId || !sessionId) {
            return res.status(400).json({
                error: 'Order ID and session ID are required'
            });
        }
        
        // Get session
        let session = userSessions.get(sessionId) || {
            id: sessionId,
            createdAt: new Date().toISOString(),
            context: {},
            messages: []
        };
        
        // Store order info in session
        session.context.orderId = orderId;
        if (customerInfo) {
            session.context.customerInfo = customerInfo;
        }
        
        userSessions.set(sessionId, session);
        
        // In a real app, you'd look up the order in your database
        // For now, we'll return mock tracking info
        const trackingInfo = generateMockTrackingInfo(orderId);
        
        res.json({
            success: true,
            orderId: orderId,
            trackingInfo: trackingInfo
        });
        
    } catch (error) {
        console.error('Order tracking error:', error);
        res.status(500).json({
            error: 'Failed to track order',
            message: 'Please try again or contact customer support.'
        });
    }
});

// Helper functions
function isOrderTrackingQuery(message) {
    const trackingKeywords = [
        'track', 'order', 'tracking', 'status', 'where is my order',
        'shipment', 'delivery', 'shipped', 'delivered'
    ];
    
    const lowerMessage = message.toLowerCase();
    return trackingKeywords.some(keyword => lowerMessage.includes(keyword));
}

async function handleOrderTracking(message, session) {
    if (session.context.orderId) {
        // User already provided order ID
        const trackingInfo = generateMockTrackingInfo(session.context.orderId);
        return `Your order ${session.context.orderId} status: ${trackingInfo.status}. ${trackingInfo.details}`;
    } else {
        // Ask for order ID
        return "I'd be happy to help you track your order! Please provide your order ID or order number.";
    }
}

async function generateResponse(message, results, session) {
  const top = Array.isArray(results) ? results.slice(0, 3) : [];
  if (top.length === 0) {
    return "I'm sorry, I couldn't find specific information about that. Could you please rephrase your question or ask about something else I might be able to help with?";
  }
  if (isProductQuery(message)) {
    return generateProductResponse(message, top);
  }
  const context = top.map(r => (r.text || '').substring(0, 300)).join('\n\n');
  return `Based on the information I found:\n\n${context}\n\nWould you like me to provide more specific details about any particular aspect?`;
}


function isProductQuery(message) {
    const productKeywords = [
        'price', 'cost', 'material', 'size', 'color', 'product',
        'buy', 'purchase', 'available', 'stock', 'features'
    ];
    
    const lowerMessage = message.toLowerCase();
    return productKeywords.some(keyword => lowerMessage.includes(keyword));
}

function generateProductResponse(message, searchResults) {
    let response = "Here's what I found about that product:\n\n";
    
    searchResults.forEach((result, index) => {
        if (result.product_info && Object.keys(result.product_info).length > 0) {
            const product = result.product_info;
            response += `**${product.name || result.title}**\n`;
            if (product.price) response += `Price: ${product.price}\n`;
            if (product.description) response += `${product.description.substring(0, 200)}...\n`;
            response += `More details: ${result.url}\n\n`;
        } else {
            response += `${result.text.substring(0, 200)}...\n`;
            response += `Source: ${result.url}\n\n`;
        }
    });
    
    return response;
}

function generateMockTrackingInfo(orderId) {
    // In a real app, this would query your order management system
    const statuses = [
        { status: 'Processing', details: 'Your order is being prepared for shipment.' },
        { status: 'Shipped', details: 'Your order has been shipped and is on its way to you.' },
        { status: 'In Transit', details: 'Your package is currently in transit to your delivery address.' },
        { status: 'Out for Delivery', details: 'Your package is out for delivery and should arrive today.' },
        { status: 'Delivered', details: 'Your order has been delivered successfully.' }
    ];
    
    // Return a random status for demo purposes
    return statuses[Math.floor(Math.random() * statuses.length)];
}

// Start server
app.listen(PORT, () => {
    console.log(`Server running on port ${PORT}`);
});
