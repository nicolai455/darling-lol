#import <AppKit/NSApplication.h>
#import <AppKit/NSSavePanel.h>
#import <Foundation/NSArray.h>

/* Darling has no Finder-tag editor. Accept the modern panel options used by
 * Electron's directory chooser without raising an unrecognized-selector error.
 * Report tags as unavailable rather than pretending to persist metadata. */
@implementation NSSavePanel (RiotTagCompatibility)
- (void)setShowsTagField:(BOOL)value { (void)value; }
- (BOOL)showsTagField { return NO; }
- (void)setShowsTags:(BOOL)value { (void)value; }
- (BOOL)showsTags { return NO; }
- (void)setTagNames:(NSArray *)names { (void)names; }
- (NSArray *)tagNames { return [NSArray array]; }
@end
