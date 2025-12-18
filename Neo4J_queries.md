# Neo4j Cypher Queries for ServiceScope

## 🌐 Access Neo4j Browser
```
URL: http://localhost:7474
Username: neo4j
Password: Ar@v!nd0495()
```

---

## 📊 Basic Queries

### View All Services and Dependencies
```cypher
MATCH (n:Service)-[r:CALLS]->(m:Service)
RETURN n, r, m
```

### Count Services
```cypher
MATCH (n:Service)
RETURN count(n) as total_services
```

### Count Dependencies
```cypher
MATCH ()-[r:CALLS]->()
RETURN count(r) as total_dependencies
```

### List All Services
```cypher
MATCH (n:Service)
RETURN n.name as service
ORDER BY service
```

---

## 🔍 Dependency Analysis

### Find What a Service Calls (Downstream)
```cypher
// What does service_a depend on?
MATCH (s:Service {name: 'service_a'})-[r:CALLS]->(target:Service)
RETURN target.name as calls, r.method as method, r.url as url
```

### Find What Calls a Service (Upstream)
```cypher
// What depends on payment_service?
MATCH (caller:Service)-[r:CALLS]->(s:Service {name: 'payment_service'})
RETURN caller.name as caller, r.method as method
```

### Find All Paths Between Two Services
```cypher
MATCH path = (a:Service {name: 'service_a'})-[r:CALLS*]->(b:Service {name: 'payment_service'})
RETURN path
```

---

## 📈 Impact Analysis

### Blast Radius (What breaks if service goes down?)
```cypher
// If payment_service fails, what's affected?
MATCH path = (dependent:Service)-[r:CALLS*]->(failed:Service {name: 'payment_service'})
RETURN DISTINCT dependent.name as affected_service, length(path) as distance
ORDER BY distance
```

### Critical Services (Most Depended Upon)
```cypher
MATCH (s:Service)<-[r:CALLS]-(caller:Service)
RETURN s.name as service, count(caller) as num_dependents
ORDER BY num_dependents DESC
LIMIT 10
```

### Isolated Services (No dependencies)
```cypher
MATCH (s:Service)
WHERE NOT (s)-[:CALLS]->() AND NOT ()-[:CALLS]->(s)
RETURN s.name as isolated_service
```

---

## 🔗 Dependency Patterns

### Circular Dependencies (Anti-pattern!)
```cypher
MATCH path = (a:Service)-[r:CALLS*]->(a)
WHERE length(path) > 1
RETURN path
LIMIT 10
```

### Longest Dependency Chain
```cypher
MATCH path = (start:Service)-[r:CALLS*]->(end:Service)
WHERE NOT ()-[:CALLS]->(start) AND NOT (end)-[:CALLS]->()
RETURN start.name, end.name, length(path) as chain_length
ORDER BY chain_length DESC
LIMIT 5
```

### Services with Most Direct Dependencies
```cypher
MATCH (s:Service)-[r:CALLS]->()
RETURN s.name as service, count(r) as direct_dependencies
ORDER BY direct_dependencies DESC
LIMIT 10
```

---

## 🎨 Visualization Queries

### Dependency Graph (All)
```cypher
MATCH (n:Service)-[r:CALLS]->(m:Service)
RETURN n, r, m
```

### Focused Graph (Specific Service + Neighbors)
```cypher
// Show service_a and everything it connects to
MATCH path = (s:Service {name: 'service_a'})-[r:CALLS*0..2]-(neighbor:Service)
RETURN path
```

### HTTP Method Distribution
```cypher
MATCH ()-[r:CALLS]->()
RETURN r.method as http_method, count(r) as count
ORDER BY count DESC
```

---

## 🧹 Maintenance Queries

### Clear All Data
```cypher
MATCH (n)
DETACH DELETE n
```

### Delete Specific Service
```cypher
MATCH (s:Service {name: 'old_service'})
DETACH DELETE s
```

### Update Service Properties
```cypher
MATCH (s:Service {name: 'payment_service'})
SET s.version = '2.0', s.status = 'active'
RETURN s
```

---

## 📊 Advanced Analysis

### Average Confidence Score
```cypher
MATCH ()-[r:CALLS]->()
WHERE r.confidence IS NOT NULL
RETURN avg(r.confidence) as avg_confidence
```

### Low Confidence Dependencies (Need Review)
```cypher
MATCH (caller:Service)-[r:CALLS]->(callee:Service)
WHERE r.confidence < 0.5
RETURN caller.name, callee.name, r.confidence, r.url
ORDER BY r.confidence
```

### Service Dependency Matrix
```cypher
MATCH (caller:Service)
OPTIONAL MATCH (caller)-[r:CALLS]->(callee:Service)
RETURN caller.name, collect(callee.name) as dependencies
ORDER BY caller.name
```

---

## 🎯 ServiceScope Specific

### Find All Payment-Related Services
```cypher
MATCH (s:Service)
WHERE s.name CONTAINS 'payment' OR s.name CONTAINS 'billing'
RETURN s.name
```

### Find Services Calling External APIs
```cypher
MATCH (s:Service)-[r:CALLS]->()
WHERE r.url CONTAINS 'http://localhost' OR r.url CONTAINS 'https://'
RETURN s.name, r.url
```

### Repository-Specific Graph
```cypher
// Note: Would need to add repository_id to nodes
MATCH (n:Service)-[r:CALLS]->(m:Service)
WHERE n.repository_id = 'your-repo-id'
RETURN n, r, m
```

---

## 💡 Tips

1. **Use LIMIT** for large graphs:
   ```cypher
   MATCH (n:Service)-[r:CALLS]->(m:Service)
   RETURN n, r, m
   LIMIT 50
   ```

2. **Profile queries** for performance:
   ```cypher
   PROFILE
   MATCH (n:Service)-[r:CALLS*1..3]->(m:Service)
   RETURN n, m
   ```

3. **Create indexes** for faster queries:
   ```cypher
   CREATE INDEX service_name FOR (n:Service) ON (n.name)
   ```

---

## 🎓 Learning Resources

- Neo4j Browser Guide: http://localhost:7474/browser/
- Cypher Manual: https://neo4j.com/docs/cypher-manual/
- Graph Algorithms: https://neo4j.com/docs/graph-data-science/

---

**Happy Graph Querying!** 🎉