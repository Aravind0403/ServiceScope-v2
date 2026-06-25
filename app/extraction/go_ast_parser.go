package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"go/ast"
	"go/printer"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
)

type ExtractedCall struct {
	Method       string `json:"method"`
	URL          string `json:"url"`
	Line         int    `json:"line"`
	URLIsDynamic bool   `json:"url_is_dynamic"`
	URLRawExpr   string `json:"url_raw_expr,omitempty"`
	File         string `json:"file"`
	Service      string `json:"service"`
}

func main() {
	if len(os.Args) < 2 {
		fmt.Println("Usage: go_ast_parser <directory_path>")
		os.Exit(1)
	}

	baseDir := os.Args[1]
	absBaseDir, err := filepath.Abs(baseDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error getting absolute path: %v\n", err)
		os.Exit(1)
	}

	calls := []ExtractedCall{}
	fset := token.NewFileSet()

	err = filepath.Walk(absBaseDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return nil
		}

		// Skip directories like .git, vendor, node_modules
		if info.IsDir() {
			name := info.Name()
			if name == ".git" || name == "vendor" || name == "node_modules" || name == "venv" || name == ".venv" {
				return filepath.SkipDir
			}
			return nil
		}

		if !strings.HasSuffix(info.Name(), ".go") {
			return nil
		}

		fileCalls := extractCallsFromFile(path, absBaseDir, fset)
		calls = append(calls, fileCalls...)
		return nil
	})

	if err != nil {
		fmt.Fprintf(os.Stderr, "Error walking directory: %v\n", err)
		os.Exit(1)
	}

	// Output as JSON
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(calls); err != nil {
		fmt.Fprintf(os.Stderr, "Error encoding output JSON: %v\n", err)
		os.Exit(1)
	}
}

func extractCallsFromFile(path, baseDir string, fset *token.FileSet) []ExtractedCall {
	fileNode, err := parser.ParseFile(fset, path, nil, 0)
	if err != nil {
		return nil
	}

	var fileCalls []ExtractedCall
	relPath, err := filepath.Rel(baseDir, path)
	if err != nil {
		relPath = path
	}

	// Service name logic: sub-directory or top-level folder
	parts := strings.Split(relPath, string(filepath.Separator))
	service := "unknown"
	if len(parts) > 0 {
		// Handle src/service_name structure
		if parts[0] == "src" || parts[0] == "services" || parts[0] == "apps" || parts[0] == "cmd" || parts[0] == "internal" {
			if len(parts) > 1 {
				service = parts[1]
			} else {
				service = parts[0]
			}
		} else {
			service = parts[0]
		}
	}

	localVars := make(map[string]ast.Expr)

	resolveArg := func(arg ast.Expr) ast.Expr {
		if ident, ok := arg.(*ast.Ident); ok {
			if resolved, found := localVars[ident.Name]; found {
				return resolved
			}
		}
		return arg
	}

	ast.Inspect(fileNode, func(n ast.Node) bool {
		if n == nil {
			return true
		}

		// Track assignments to local variables
		if assign, ok := n.(*ast.AssignStmt); ok {
			for i, lhs := range assign.Lhs {
				if i >= len(assign.Rhs) {
					break
				}
				if ident, ok := lhs.(*ast.Ident); ok {
					rhs := assign.Rhs[i]
					// If RHS is mustCreateClient(arg), resolve to arg
					if call, ok := rhs.(*ast.CallExpr); ok {
						var funcName string
						if sel, ok := call.Fun.(*ast.SelectorExpr); ok {
							funcName = sel.Sel.Name
						} else if id, ok := call.Fun.(*ast.Ident); ok {
							funcName = id.Name
						}
						if (funcName == "mustCreateClient" || funcName == "mustCreateGrpcClient") && len(call.Args) >= 1 {
							localVars[ident.Name] = call.Args[0]
						} else {
							localVars[ident.Name] = rhs
						}
					} else {
						localVars[ident.Name] = rhs
					}
				}
			}
			return true
		}

		call, ok := n.(*ast.CallExpr)
		if !ok {
			return true
		}

		// Check if it's a SelectorExpr e.g. http.Get or client.Get
		if selector, ok := call.Fun.(*ast.SelectorExpr); ok {
			method := strings.ToLower(selector.Sel.Name)

			// 1. Standard http library calls
			if ident, ok := selector.X.(*ast.Ident); ok && ident.Name == "http" {
				if method == "get" || method == "post" || method == "postform" {
					if len(call.Args) >= 1 {
						extracted := createExtractedCall(method, resolveArg(call.Args[0]), fset, relPath, service)
						fileCalls = append(fileCalls, extracted)
					}
				} else if method == "newrequest" || method == "newrequestwithcontext" {
					urlArgIdx := 1
					methodArgIdx := 0
					if method == "newrequestwithcontext" {
						urlArgIdx = 2
						methodArgIdx = 1
					}
					if len(call.Args) > urlArgIdx {
						reqMethod := "get"
						if methodLit, ok := call.Args[methodArgIdx].(*ast.BasicLit); ok && methodLit.Kind == token.STRING {
							reqMethod = strings.ToLower(strings.Trim(methodLit.Value, "\"`"))
						} else {
							// Try to use a variable method or default to lower method
							reqMethod = renderNode(call.Args[methodArgIdx], fset)
						}
						extracted := createExtractedCall(reqMethod, resolveArg(call.Args[urlArgIdx]), fset, relPath, service)
						fileCalls = append(fileCalls, extracted)
					}
				}
			}

			// 2. grpc library calls
			if ident, ok := selector.X.(*ast.Ident); ok && ident.Name == "grpc" {
				if method == "dial" || method == "dialcontext" || method == "newclient" {
					targetArgIdx := 0
					if method == "dialcontext" {
						targetArgIdx = 1
					}
					if len(call.Args) > targetArgIdx {
						extracted := createExtractedCall("grpc", resolveArg(call.Args[targetArgIdx]), fset, relPath, service)
						fileCalls = append(fileCalls, extracted)
					}
				}
			}

			// 3. Generic Client calls (resty, etc.)
			// Match common HTTP methods Get, Post, Put, Delete, Patch
			if method == "get" || method == "post" || method == "put" || method == "delete" || method == "patch" {
				// Prevent matching standard http calls (handled above)
				isStdHttp := false
				if ident, ok := selector.X.(*ast.Ident); ok && ident.Name == "http" {
					isStdHttp = true
				}
				if !isStdHttp && len(call.Args) >= 1 {
					extracted := createExtractedCall(method, resolveArg(call.Args[0]), fset, relPath, service)
					// Apply require_absolute guard for generic client calls if the URL is static
					if !extracted.URLIsDynamic {
						if strings.HasPrefix(extracted.URL, "http://") || strings.HasPrefix(extracted.URL, "https://") {
							fileCalls = append(fileCalls, extracted)
						}
					} else {
						fileCalls = append(fileCalls, extracted)
					}
				}
			}
		}

		// 4. Custom Client/Clientset constructor calls (e.g. NewRepoServerClientset)
		var funcName string
		if selector, ok := call.Fun.(*ast.SelectorExpr); ok {
			funcName = selector.Sel.Name
		} else if ident, ok := call.Fun.(*ast.Ident); ok {
			funcName = ident.Name
		}

		if funcName != "" {
			if strings.HasPrefix(funcName, "New") && (strings.Contains(funcName, "Client") || strings.Contains(funcName, "Clientset")) {
				isStdLib := false
				if selector, ok := call.Fun.(*ast.SelectorExpr); ok {
					if ident, ok := selector.X.(*ast.Ident); ok && (ident.Name == "http" || ident.Name == "grpc") {
						isStdLib = true
					}
				}
				if !isStdLib && len(call.Args) >= 1 {
					extracted := createExtractedCall("grpc", resolveArg(call.Args[0]), fset, relPath, service)
					fileCalls = append(fileCalls, extracted)
				}
			}
		}

		return true
	})

	return fileCalls
}

func createExtractedCall(method string, arg ast.Expr, fset *token.FileSet, file, service string) ExtractedCall {
	url, isDynamic, rawExpr := parseURLExpr(arg, fset)
	line := fset.Position(arg.Pos()).Line

	return ExtractedCall{
		Method:       method,
		URL:          url,
		Line:         line,
		URLIsDynamic: isDynamic,
		URLRawExpr:   rawExpr,
		File:         file,
		Service:      service,
	}
}

func parseURLExpr(expr ast.Expr, fset *token.FileSet) (url string, isDynamic bool, rawExpr string) {
	switch node := expr.(type) {
	case *ast.BasicLit:
		if node.Kind == token.STRING {
			val := strings.Trim(node.Value, "\"`")
			return val, false, ""
		}
	case *ast.Ident:
		return fmt.Sprintf("<dynamic:%s>", node.Name), true, node.Name

	case *ast.CallExpr:
		// Check for os.Getenv("VAR")
		if selector, ok := node.Fun.(*ast.SelectorExpr); ok {
			if ident, ok := selector.X.(*ast.Ident); ok && ident.Name == "os" && selector.Sel.Name == "Getenv" {
				if len(node.Args) == 1 {
					if lit, ok := node.Args[0].(*ast.BasicLit); ok && lit.Kind == token.STRING {
						varName := strings.Trim(lit.Value, "\"`")
						return fmt.Sprintf("<dynamic:%s>", varName), true, renderNode(node, fset)
					}
				}
			}
			// Check for fmt.Sprintf("http://...", args...)
			if ident, ok := selector.X.(*ast.Ident); ok && ident.Name == "fmt" && selector.Sel.Name == "Sprintf" {
				if len(node.Args) >= 1 {
					if lit, ok := node.Args[0].(*ast.BasicLit); ok && lit.Kind == token.STRING {
						fmtStr := strings.Trim(lit.Value, "\"`")
						// Extract static prefix if it starts with http
						if strings.HasPrefix(fmtStr, "http") {
							// Find index of first % placeholder or parse up to it
							idx := strings.Index(fmtStr, "%")
							if idx != -1 {
								return fmtStr[:idx], true, renderNode(node, fset)
							}
							return fmtStr, true, renderNode(node, fset)
						}
					}
				}
			}
		}
		// Generic function call
		exprStr := renderNode(node, fset)
		return fmt.Sprintf("<dynamic:%s>", exprStr), true, exprStr

	case *ast.BinaryExpr:
		// String concatenation: left + right
		if node.Op == token.ADD {
			leftStr, leftDyn, _ := parseURLExpr(node.X, fset)
			exprStr := renderNode(node, fset)

			if !leftDyn && strings.HasPrefix(leftStr, "http") {
				return leftStr, true, exprStr
			}
			if leftDyn {
				return leftStr, true, exprStr
			}
			return fmt.Sprintf("<dynamic:%s>", exprStr), true, exprStr
		}
	}

	// Fallback
	exprStr := renderNode(expr, fset)
	return fmt.Sprintf("<dynamic:%s>", exprStr), true, exprStr
}

func renderNode(node ast.Node, fset *token.FileSet) string {
	var buf bytes.Buffer
	if err := printer.Fprint(&buf, fset, node); err != nil {
		return ""
	}
	return buf.String()
}
