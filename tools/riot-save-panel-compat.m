#import <AppKit/NSApplication.h>
#import <AppKit/NSSavePanel.h>
#import <Foundation/NSArray.h>

/* Darling has no Finder-tag editor. Accept the modern panel options used by
 * Electron's directory chooser without raising an unrecognized-selector error.
 * Report tags as unavailable rather than pretending to persist metadata.
 * This intentionally differs from macOS: showsTagField defaults to YES there,
 * and tagNames normally retains the panel's initial tag state. NSOpenPanel
 * inherits these no-op methods from NSSavePanel. */
@implementation NSSavePanel (RiotTagCompatibility)
- (void)setShowsTagField:(BOOL)value { (void)value; }
- (BOOL)showsTagField { return NO; }
- (void)setTagNames:(NSArray *)names { (void)names; }
- (NSArray *)tagNames { return [NSArray array]; }
@end
