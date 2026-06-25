#!/usr/bin/env python3
"""
Unit tests for the Tree-sitter Polyglot AST Call Extractor.
"""

import textwrap
import tempfile
import os
import pytest

from app.extraction.extract_polyglot_calls import extract_calls_from_source

def test_java_rest_template_and_webclient():
    code = """
    package com.example.service;
    
    import org.springframework.web.client.RestTemplate;
    import org.springframework.web.reactive.function.client.WebClient;
    
    public class OrderClient {
        private final RestTemplate restTemplate = new RestTemplate();
        private final WebClient webClient = WebClient.builder().build();
        
        public void process() {
            String paymentUrl = System.getenv("PAYMENT_SERVICE_URL");
            restTemplate.getForObject(paymentUrl, Payment.class);
            restTemplate.postForObject("http://billing-service/charge", request, Billing.class);
            
            webClient.get()
                     .uri("http://inventory-service/stock")
                     .retrieve()
                     .bodyToMono(Stock.class);
                     
            ShippingGrpc.newBlockingStub(channel);
        }
    }
    """
    calls = extract_calls_from_source(code, "OrderClient.java", "java", "order-service")
    assert len(calls) == 4
    
    # 1. restTemplate.getForObject (dynamic)
    c1 = [c for c in calls if c["method"] == "get" and c["url_is_dynamic"]][0]
    assert c1["url"] == "<dynamic:PAYMENT_SERVICE_URL>"
    assert c1["url_raw_expr"] == 'System.getenv("PAYMENT_SERVICE_URL")'
    
    # 2. restTemplate.postForObject (static)
    c2 = [c for c in calls if c["method"] == "post"][0]
    assert c2["url"] == "http://billing-service/charge"
    assert not c2["url_is_dynamic"]
    
    # 3. webClient.get() uri (static)
    c3 = [c for c in calls if c["url"] == "http://inventory-service/stock"][0]
    assert c3["method"] == "get"
    
    # 4. ShippingGrpc.newBlockingStub
    c4 = [c for c in calls if c["method"] == "grpc"][0]
    assert c4["url"] == "<dynamic:channel>"

def test_javascript_typescript_axios_and_fetch():
    code = """
    const axios = require('axios');
    
    async function getCheckout() {
        const paymentAddr = process.env.PAYMENT_SERVICE_ADDR;
        const res = await axios.post(paymentAddr, { amount: 100 });
        
        const configUrl = process.env['CONFIG_URL'];
        const metadata = await fetch(configUrl);
        
        const client = new HelloServiceClient("localhost:50051", grpc.credentials.createInsecure());
    }
    """
    calls = extract_calls_from_source(code, "checkout.js", "javascript", "checkout-service")
    assert len(calls) == 3
    
    # 1. axios.post (dynamic env)
    c1 = [c for c in calls if c["method"] == "post"][0]
    assert c1["url"] == "<dynamic:PAYMENT_SERVICE_ADDR>"
    assert c1["url_is_dynamic"]
    
    # 2. fetch (dynamic indexing env)
    c2 = [c for c in calls if c["method"] == "get"][0]
    assert c2["url"] == "<dynamic:CONFIG_URL>"
    assert c2["url_is_dynamic"]
    
    # 3. new HelloServiceClient
    c3 = [c for c in calls if c["method"] == "grpc"][0]
    assert c3["url"] == "localhost:50051"
    assert not c3["url_is_dynamic"]

def test_csharp_httpclient_and_grpc():
    code = """
    using System;
    using System.Net.Http;
    using Grpc.Net.Client;
    
    public class CartService {
        private static readonly HttpClient client = new HttpClient();
        
        public async Task Checkout() {
            var dbUrl = Environment.GetEnvironmentVariable("DB_CONNECTION_URL");
            var response = await client.GetAsync(dbUrl);
            
            var channel = GrpcChannel.ForAddress("http://reposerver:50051");
            var repoClient = new RepoServerServiceClient(channel);
        }
    }
    """
    calls = extract_calls_from_source(code, "CartService.cs", "c_sharp", "cart-service")
    assert len(calls) == 3
    
    # 1. client.GetAsync (dynamic env)
    c1 = [c for c in calls if c["method"] == "get"][0]
    assert c1["url"] == "<dynamic:DB_CONNECTION_URL>"
    assert c1["url_is_dynamic"]
    
    # 2. GrpcChannel.ForAddress
    c2 = [c for c in calls if c["method"] == "grpc" and c["url"] == "http://reposerver:50051"][0]
    assert not c2["url_is_dynamic"]
    
    # 3. new RepoServerServiceClient
    c3 = [c for c in calls if c["method"] == "grpc" and c["url"] == "<dynamic:channel>"][0]
    assert c3["url_is_dynamic"]
