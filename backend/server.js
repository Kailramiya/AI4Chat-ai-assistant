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
    origin: process.env.ALLOWED_ORIGINS ? process.env.ALLOWED_ORIGINS.split(',') : ['http://localhost:3000','http://127.0.0.1:3000','https://ai-4-chat-ai-assistant.vercel.app/'],
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


function isPersonalizedQuery(message) {
    const personalKeywords = [
        'my order', 'my refund', 'my account', 'my purchase',
        'my delivery', 'my package', 'my return', 'my payment',
        'my shipping', 'i ordered', 'i bought', 'i purchased',
        'i paid', 'i returned'
    ];
    
    const lowerMessage = message.toLowerCase();
    return personalKeywords.some(keyword => lowerMessage.includes(keyword));
}

function handlePersonalizedQuery(message) {
    // Extract query type
    const lowerMessage = message.toLowerCase();
    
    if (lowerMessage.includes('order') || lowerMessage.includes('delivery') || lowerMessage.includes('package')) {
        return "To check your order status, please provide your order number. If you don't have it, you can find it in your order confirmation email.";
    }
    
    if (lowerMessage.includes('refund')) {
        return "To check your refund status, please provide your order number and the date of your refund request. You can also check your refund status in your account dashboard.";
    }
    
    if (lowerMessage.includes('return')) {
        return "For return status, please provide your return authorization number. You can find this in your return confirmation email.";
    }
    
    if (lowerMessage.includes('payment')) {
        return "For payment-related queries, please check your order confirmation email or your account dashboard. For security reasons, I can't access specific payment details here.";
    }
    
    return "I notice you're asking about your personal information. To help you better, please provide relevant details like your order number or reference number. Alternatively, you can check your account dashboard for this information.";
}

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
        console.log('Received message:', message, 'Session ID:', sessionId);
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
         response = await generateResponse(message, normResults, session);
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



// async function generateResponse(message, results, session) {
//   const top = Array.isArray(results) ? results.slice(0, 3) : [];
//   if (top.length === 0) {
//     return "I'm sorry, I couldn't find specific information about that. Could you please rephrase your question or ask about something else I might be able to help with?";
//   }
//   if (isProductQuery(message)) {
//     return generateProductResponse(message, top);
//   }
//   const context = top.map(r => (r.text || '').substring(0, 300)).join('\n\n');
//   return `Based on the information I found:\n\n${context}\n\nWould you like me to provide more specific details about any particular aspect?`;
// }


function isProductQuery(message) {
    const productKeywords = [
        'price', 'cost', 'material', 'size', 'color', 'product',
        'buy', 'purchase', 'available', 'stock', 'features'
    ];
    
    const lowerMessage = message.toLowerCase();
    return productKeywords.some(keyword => lowerMessage.includes(keyword));
}

function filterByAttributes(hits, color, size) {
  if (!color && !size) return hits;
  const pick = [];
  for (const h of hits) {
    const pi = h.product_info || {};
    const variants = Array.isArray(pi.variants) ? pi.variants : [];
    const hasVariant = variants.some(v =>
      (!color || (v.color || '').toLowerCase() === color) &&
      (!size || (v.size || '').toLowerCase() === size)
    );
    const text = (h.text || '').toLowerCase();
    const okText = (!color || text.includes(color)) && (!size || text.includes(size));
    if (hasVariant || okText) pick.push(h);
  }
  return pick.length ? pick : hits;
}

function formatProductAnswer(query, hits) {
  const lower = query.toLowerCase();

  // intents
  const priceIntent = /(price|cost|how much|₹|\$)/i.test(lower);
  const availabilityIntent = /(available|in stock|out of stock|stock)/i.test(lower);
  const materialIntent = /(material|quality|fabric|cotton|leather|steel|wash|care|durable|handmade)/i.test(lower);
  const optionsIntent = /(size|sizes|color|colour|colors|options|variants)/i.test(lower);
  const shippingIntent = /(shipping|delivery|returns|refund|warranty policy|return policy)/i.test(lower);
  const warrantyIntent = /(warranty|guarantee)/i.test(lower);
  const imageIntent = /(image|photo|picture)/i.test(lower);
  const weightIntent = /(weight|heavy|light)/i.test(lower);

  // attributes
  const color = (lower.match(/\b(blue|green|purple|red|black|white|gold|silver)\b/) || [])[1];
  const sizeRaw = (lower.match(/\b(xs|s|m|l|xl|xxl|small|medium|large)\b/) || [])[1];
  const size = sizeRaw ? sizeRaw.replace('small','s').replace('medium','m').replace('large','l') : null;

  // dedupe by URL
  const seen = new Set();
  const unique = [];
  for (const h of hits) {
    if (h.url && !seen.has(h.url)) {
      seen.add(h.url);
      unique.push(h);
    }
  }

  // filter by requested attributes, then take one best
  const filtered = filterByAttributes(unique, color, size);
  const picked = filtered.slice(0, 1);

  const out = [];
  for (const r of picked) {
    const pi = r.product_info || {};
    const title = r.title || 'Product';
    const url = r.url || '';
    const snippet = (r.text || '').slice(0, 220).trim();
    const variants = Array.isArray(pi.variants) ? pi.variants : [];
    const vMatch = variants.find(v =>
      (!color || (v.color || '').toLowerCase() === color) &&
      (!size || (v.size || '').toLowerCase() === size)
    ) || variants[0];

    // primary image if present
    const images = Array.isArray(pi.images) ? pi.images : [];
    const mainImage = images.length ? images[0] : null;
    const mainImageSrc = mainImage && (mainImage.src || mainImage.url || mainImage.image || '');

    // facts from new fields
    const warranty = (pi.warranty || '').trim();
    const shippingInfo = (pi.shipping_info || '').trim();
    const materials = (pi.materials || '').trim();
    const care = (pi.care || '').trim();

    // build response lines
    let lines = [title];

    // Price and discount handling
    if (priceIntent && (vMatch || pi.best_price)) {
      if (vMatch && vMatch.price) {
        const cur = vMatch.price;
        const was = (vMatch.compare_at_price || '').trim();
        const avail = vMatch.available ? '(in stock)' : '(out of stock)';
        if (was) {
          lines.push(`Price: ${cur} (was ${was}) ${avail}`);
        } else {
          lines.push(`Price: ${cur} ${avail}`);
        }
      } else if (pi.best_price) {
        const range = (pi.price_range || '').trim();
        lines.push(`Price from: ${range || pi.best_price}`);
      }
    }

    // Availability handling
    if (availabilityIntent && vMatch) {
      lines.push(`Availability: ${vMatch.available ? 'in stock' : 'out of stock'}`);
      if (vMatch.price) {
        const was = (vMatch.compare_at_price || '').trim();
        lines.push(`Price: ${vMatch.price}${was ? ` (was ${was})` : ''}`);
      }
    }

    // Materials / Care
    if (materialIntent) {
      if (materials) lines.push(`Materials: ${materials}`);
      if (care) lines.push(`Care: ${care}`);
      if (!materials && !care) lines.push(snippet + '…');
    }

    // Options: show colors/sizes lists
    if (optionsIntent) {
      if (variants.length) {
        const colors = [...new Set(variants.map(v => (v.color || '').trim()).filter(Boolean))];
        const sizes = [...new Set(variants.map(v => (v.size || '').trim()).filter(Boolean))];
        if (colors.length) lines.push(`Colors: ${colors.join(', ')}`);
        if (sizes.length) lines.push(`Sizes: ${sizes.join(', ')}`);
      } else {
        lines.push(snippet + '…');
      }
    }

    // Warranty
    if (warrantyIntent) {
      if (warranty) {
        lines.push(`Warranty: ${warranty}`);
      } else {
        lines.push('Warranty details not specified on the product page.');
      }
    }

    // Shipping / Returns policy
    if (shippingIntent) {
      if (shippingInfo) {
        lines.push(`Shipping: ${shippingInfo}`);
      } else {
        lines.push('Shipping/returns details not specified here. Check the store policy page via the link below.');
      }
    }

    // Image
    if (imageIntent) {
      if (mainImageSrc) {
        lines.push(`Image: ${mainImageSrc}`);
      } else {
        lines.push('No image found in metadata; see product page.');
      }
    }

    // Weight
    if (weightIntent && vMatch) {
      const w = (vMatch.weight != null && vMatch.weight !== '') ? vMatch.weight : null;
      const wu = (vMatch.weight_unit || '').trim();
      if (w) {
        lines.push(`Weight: ${w}${wu ? ' ' + wu : ''}`);
      } else {
        lines.push('Weight not specified for this variant.');
      }
    }

    // General fallback when no specific intent triggered
    if (
      !priceIntent && !availabilityIntent && !materialIntent &&
      !optionsIntent && !warrantyIntent && !shippingIntent &&
      !imageIntent && !weightIntent
    ) {
      // brief general answer that includes price-from if available
      if (pi.best_price) lines.push(`Price from: ${pi.best_price}`);
      if (materials) lines.push(`Materials: ${materials}`);
      if (care) lines.push(`Care: ${care}`);
      if (variants.length && vMatch && typeof vMatch.available === 'boolean') {
        lines.push(`Availability: ${vMatch.available ? 'in stock' : 'out of stock'}`);
      }
      if (lines.length === 1) {
        lines.push(snippet + '…');
      }
    }

    lines.push(`More details: ${url}`);
    out.push(lines.join('\n'));
  }

  return out.join('\n\n');
}



function dedupeByUrl(hits) {
  const seen = new Set();
  const out = [];
  for (const h of hits) {
    if (h.url && !seen.has(h.url)) {
      seen.add(h.url);
      out.push(h);
    }
  }
  return out;
}



async function generateResponse(message, results, session) {
  if (isPersonalizedQuery(message)) {
        return handlePersonalizedQuery(message);
    }
  const top = Array.isArray(results) ? results.slice(0, 3) : [];
  if (top.length === 0) {
    return "I'm sorry, I couldn't find specific information about that. Could you please rephrase your question or ask about something else I might be able to help with?";
  }
  if (isProductQuery(message)) {
  return formatProductAnswer(message, top);
}

  const context = top.map(r => (r.text || '').substring(0, 300)).join('\n\n');
  return `Based on the information I found:\n\n${context}\n\nWould you like me to provide more specific details about any particular aspect?`;
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
