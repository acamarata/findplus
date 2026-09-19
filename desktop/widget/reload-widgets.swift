import Foundation
import WidgetKit

WidgetCenter.shared.reloadAllTimelines()
// reloadAllTimelines() hands the request to widgetkitd asynchronously and has
// no completion handler; exiting immediately can drop it. Service the run loop
// briefly so the message is delivered before the process goes away.
RunLoop.main.run(until: Date().addingTimeInterval(0.5))
