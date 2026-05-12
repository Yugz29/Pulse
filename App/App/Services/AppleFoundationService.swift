import Foundation

#if canImport(FoundationModels)
import FoundationModels
#endif

struct AppleFoundationCompletionResult {
    let text: String
    let status: String
    let error: String?
}

final class AppleFoundationService {
    func isAvailable() async -> Bool {
        #if canImport(FoundationModels)
        if #available(macOS 26.0, *) {
            return SystemLanguageModel.default.isAvailable
        }
        #endif
        return false
    }

    func complete(prompt: String, maxTokens: Int?) async -> AppleFoundationCompletionResult {
        let trimmedPrompt = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedPrompt.isEmpty else {
            return AppleFoundationCompletionResult(text: "", status: "failed", error: "empty_prompt")
        }

        #if canImport(FoundationModels)
        if #available(macOS 26.0, *) {
            let model = SystemLanguageModel.default
            guard model.isAvailable else {
                return AppleFoundationCompletionResult(
                    text: "",
                    status: "failed",
                    error: "apple_foundation_unavailable"
                )
            }

            do {
                let instructions = """
                Tu réponds uniquement avec du texte final en français. N'utilise aucun outil.
                """
                let session = LanguageModelSession(instructions: instructions)
                let options = GenerationOptions(
                    sampling: nil,
                    temperature: 0.2,
                    maximumResponseTokens: maxTokens
                )
                let response = try await session.respond(to: trimmedPrompt, options: options)
                return AppleFoundationCompletionResult(
                    text: response.content.trimmingCharacters(in: .whitespacesAndNewlines),
                    status: "generated",
                    error: nil
                )
            } catch {
                return AppleFoundationCompletionResult(
                    text: "",
                    status: "failed",
                    error: String(describing: error)
                )
            }
        }
        #endif

        return AppleFoundationCompletionResult(
            text: "",
            status: "failed",
            error: "foundation_models_framework_unavailable"
        )
    }
}
