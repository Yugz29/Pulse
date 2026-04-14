import Foundation

struct DaemonBridge {
    let base: String
    let session: URLSession

    nonisolated init(
        base: String = "http://127.0.0.1:8765",
        session: URLSession = .shared
    ) {
        self.base = base
        self.session = session
    }

    func makeURL(_ path: String) throws -> URL {
        guard let url = URL(string: "\(base)\(path)") else {
            throw DaemonError.invalidURL
        }
        return url
    }

    func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try JSONDecoder().decode(type, from: data)
        } catch {
            throw DaemonError.from(error)
        }
    }

    func validate(_ response: URLResponse, expectedStatus: Int) throws {
        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == expectedStatus else {
            throw DaemonError.badStatus((response as? HTTPURLResponse)?.statusCode ?? -1)
        }
    }

    func data(from url: URL) async throws -> (Data, URLResponse) {
        do {
            return try await session.data(from: url)
        } catch {
            throw DaemonError.from(error)
        }
    }

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        do {
            return try await session.data(for: request)
        } catch {
            throw DaemonError.from(error)
        }
    }

    func bytes(for request: URLRequest) async throws -> (URLSession.AsyncBytes, URLResponse) {
        do {
            return try await session.bytes(for: request)
        } catch {
            throw DaemonError.from(error)
        }
    }

    func jsonRequest(path: String, body: Encodable, timeout: TimeInterval = 30) throws -> URLRequest {
        let requestBody = try JSONEncoder().encode(AnyEncodable(body))
        var request = URLRequest(url: try makeURL(path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = timeout
        request.httpBody = requestBody
        return request
    }

    func jsonObjectRequest(path: String, body: [String: Any], timeout: TimeInterval = 30) throws -> URLRequest {
        var request = URLRequest(url: try makeURL(path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = timeout
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        return request
    }

    func post(path: String) async throws {
        var request = URLRequest(url: try makeURL(path))
        request.httpMethod = "POST"
        request.timeoutInterval = 3
        let (_, response) = try await data(for: request)
        try validate(response, expectedStatus: 200)
    }
}

private struct AnyEncodable: Encodable {
    private let encodeValue: (Encoder) throws -> Void

    init(_ wrapped: Encodable) {
        self.encodeValue = wrapped.encode
    }

    func encode(to encoder: Encoder) throws {
        try encodeValue(encoder)
    }
}
