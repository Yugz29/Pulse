import SwiftUI

struct NotchPanelShape: Shape {

    var bottomCornerRadius: CGFloat = 16
    var notchWidth:         CGFloat
    var notchHeight:        CGFloat
    var panelWidth:         CGFloat
    var panelHeight:        CGFloat

    // Rayon des coins de l'encoche hardware
    private let hardwareNotchRadius: CGFloat = 8

    var animatableData: AnimatablePair<AnimatablePair<CGFloat, CGFloat>, AnimatablePair<CGFloat, CGFloat>> {
        get { .init(.init(panelWidth, panelHeight), .init(bottomCornerRadius, notchWidth)) }
        set {
            panelWidth         = newValue.first.first
            panelHeight        = newValue.first.second
            bottomCornerRadius = newValue.second.first
            notchWidth         = newValue.second.second
        }
    }

    func path(in rect: CGRect) -> Path {
        let midX = rect.midX
        if panelHeight <= 0 { return closedNotchPath(midX: midX) }
        // Startup animation — même largeur que l'encoche
        if panelWidth <= notchWidth + 1 { return straightExtensionPath(midX: midX) }
        return openPanelPath(midX: midX)
    }

    // MARK: - Encoche fermée (idle)

    private func closedNotchPath(midX: CGFloat) -> Path {
        let left  = midX - notchWidth / 2
        let right = midX + notchWidth / 2
        let r     = hardwareNotchRadius

        var path = Path()
        path.move(to: CGPoint(x: left, y: 0))
        path.addLine(to: CGPoint(x: left, y: notchHeight - r))
        path.addQuadCurve(to: CGPoint(x: left + r, y: notchHeight),
                          control: CGPoint(x: left, y: notchHeight))
        path.addLine(to: CGPoint(x: right - r, y: notchHeight))
        path.addQuadCurve(to: CGPoint(x: right, y: notchHeight - r),
                          control: CGPoint(x: right, y: notchHeight))
        path.addLine(to: CGPoint(x: right, y: 0))
        path.closeSubpath()
        return path
    }

    // MARK: - Extension startup (même largeur que l'encoche)

    private func straightExtensionPath(midX: CGFloat) -> Path {
        let left   = midX - notchWidth / 2
        let right  = midX + notchWidth / 2
        let r      = hardwareNotchRadius
        let bottom = notchHeight + panelHeight

        var path = Path()
        path.move(to: CGPoint(x: left, y: 0))
        path.addLine(to: CGPoint(x: left, y: bottom - r))
        path.addQuadCurve(to: CGPoint(x: left + r, y: bottom),
                          control: CGPoint(x: left, y: bottom))
        path.addLine(to: CGPoint(x: right - r, y: bottom))
        path.addQuadCurve(to: CGPoint(x: right, y: bottom - r),
                          control: CGPoint(x: right, y: bottom))
        path.addLine(to: CGPoint(x: right, y: 0))
        path.closeSubpath()
        return path
    }

    // MARK: - Panel ouvert — rectangle plat collé au bord écran
    //
    // Pas de courbes d'épaules. Le bord supérieur est une ligne droite
    // de panelLeft à panelRight à y=0. L'encoche hardware crée naturellement
    // la découpe visible, exactement comme NotchNook.

    private func openPanelPath(midX: CGFloat) -> Path {
        let left   = midX - panelWidth / 2
        let right  = midX + panelWidth / 2
        let r      = bottomCornerRadius
        let bottom = notchHeight + panelHeight

        var path = Path()

        // Bord supérieur gauche — droit, collé au bord écran
        path.move(to: CGPoint(x: left, y: 0))

        // Descente gauche + coin bas-gauche arrondi
        path.addLine(to: CGPoint(x: left, y: bottom - r))
        path.addQuadCurve(to: CGPoint(x: left + r, y: bottom),
                          control: CGPoint(x: left, y: bottom))

        // Bord bas
        path.addLine(to: CGPoint(x: right - r, y: bottom))

        // Coin bas-droit arrondi
        path.addQuadCurve(to: CGPoint(x: right, y: bottom - r),
                          control: CGPoint(x: right, y: bottom))

        // Remontée droite — droit, collé au bord écran
        path.addLine(to: CGPoint(x: right, y: 0))

        path.closeSubpath()
        return path
    }
}
